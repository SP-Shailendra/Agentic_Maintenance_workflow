import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import get_settings
from app.main import app


def test_runtime_is_recreated_for_each_app_lifespan() -> None:
    with TestClient(app):
        first_runtime = app.state.runtime
        assert first_runtime.pipeline._task is not None

    with TestClient(app):
        second_runtime = app.state.runtime
        assert second_runtime is not first_runtime
        assert second_runtime.pipeline._task is not None


def test_invalid_settings_fail_fast_during_startup(monkeypatch) -> None:
    monkeypatch.setenv("HITL_MIN_CONFIDENCE", "not-a-number")
    get_settings.cache_clear()
    try:
        with pytest.raises(ValidationError):
            with TestClient(app):
                pass
    finally:
        get_settings.cache_clear()


def test_simulator_config_reload_speed_and_run_replay() -> None:
    with TestClient(app) as client:
        config = client.get("/api/v1/simulator/config")
        assert config.status_code == 200
        config_data = config.json()
        assert len(config_data["config_hash"]) == 64
        assert config_data["master_seed"] == 17

        speed = client.post("/api/v1/simulator/speed", json={"speed": 10})
        assert speed.status_code == 200
        assert speed.json()["sleep_seconds"] == config_data["tick_seconds"] / 10

        started = client.post(
            "/api/v1/simulator/runs",
            json={"asset_id": "WD-001", "scenario": "healthy", "seed": 17},
        )
        assert started.status_code == 200
        run_id = started.json()["ground_truth"]["scenario_id"]
        run = client.get(f"/api/v1/simulator/runs/{run_id}")
        assert run.status_code == 200
        assert run.json()["config_hash"] == config_data["config_hash"]

        replay = client.post(f"/api/v1/simulator/runs/{run_id}/replay")
        assert replay.status_code == 200
        assert replay.json()["ground_truth"]["scenario"] == "healthy"

        reloaded = client.post("/api/v1/simulator/config/reload")
        assert reloaded.status_code == 200
        assert reloaded.json()["config_hash"] == config_data["config_hash"]


def test_simulator_config_update_parameters_undo_and_run_exports(monkeypatch) -> None:
    monkeypatch.setattr("app.runtime.write_simulator_configuration", lambda configuration: None)
    with TestClient(app) as client:
        original_config = client.get("/api/v1/simulator/config").json()
        updated_config = original_config["configuration"]
        updated_config["master_seed"] = 23
        updated = client.put("/api/v1/simulator/config", json=updated_config)
        assert updated.status_code == 200
        assert updated.json()["master_seed"] == 23

        parameters = {
            "baseline_scale": 1.05,
            "load_scale": 0.9,
            "thermal_time_constant_scale": 1.1,
        }
        changed = client.post("/api/v1/simulator/assets/WD-001/parameters", json=parameters)
        assert changed.status_code == 200
        assert changed.json()["parameters"] == parameters
        undone = client.post("/api/v1/simulator/assets/WD-001/parameters/undo")
        assert undone.status_code == 200
        assert undone.json()["parameters"]["baseline_scale"] == 1.0
        audit = client.get("/api/v1/audit").json()
        assert any(item["event_type"] == "simulator_asset_parameters_updated" for item in audit)
        assert client.get("/api/v1/audit/verify").json()["ok"] is True

        started = client.post(
            "/api/v1/simulator/runs",
            json={"asset_id": "WD-001", "scenario": "bearing_wear", "seed": 31},
        )
        assert started.status_code == 200
        run_id = started.json()["ground_truth"]["scenario_id"]
        csv_export = client.get(f"/api/v1/simulator/runs/{run_id}/export?format=csv")
        assert csv_export.status_code == 200
        assert "scenario_id" in csv_export.text
        ndjson_export = client.get(f"/api/v1/simulator/runs/{run_id}/export?format=ndjson")
        assert ndjson_export.status_code == 200
        assert run_id in ndjson_export.text
        parquet_export = client.get(f"/api/v1/simulator/runs/{run_id}/export?format=parquet")
        assert parquet_export.status_code == 200
        assert parquet_export.content.startswith(b"PAR1")
        assert parquet_export.content.endswith(b"PAR1")


def test_raw_vibration_api_is_separate_from_scalar_telemetry() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/simulator/assets/WD-001/vibration?severity=0.8")
        assert response.status_code == 200
        window = response.json()
        assert window["unit"] == "m/s^2"
        assert len(window["samples"]) == 12800
        assert window["bpfo_hz"] < window["sample_rate_hz"] / 2
        assert client.get("/api/v1/simulator/assets/missing/vibration").status_code == 404
        assert client.get("/api/v1/simulator/assets/WD-001/vibration?severity=2").status_code == 422


def test_sensor_fault_endpoint_uses_separate_scenario_label() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/simulator/sensor-faults",
            json={
                "asset_id": "WD-001",
                "fault": "spike",
                "duration_ticks": 10,
                "seed": 31,
                "measurement_type": "current",
            },
        )
        assert response.status_code == 200
        ground_truth = response.json()["ground_truth"]
        assert ground_truth["scenario"] == "sensor_spike"
        assert ground_truth["scenario_id"]


def test_health_system_config_and_seeded_fleet() -> None:
    with TestClient(app) as client:
        assert client.get("/api/v1/health").json()["status"] == "ok"
        config = client.get("/api/v1/system/config").json()
        assert config["guardrails"]["human_approval_always_required"] is True
        assets = client.get("/api/v1/assets").json()
        assert len(assets) == 5
        assert (
            next(asset for asset in assets if asset["asset_id"] == "IC-002")["safety_critical"]
            is None
        )


def test_scenario_creates_approval_and_records_approver() -> None:
    with TestClient(app) as client:
        runtime = app.state.runtime
        client.post("/api/v1/simulator/reset")
        result = client.post(
            "/api/v1/simulator/scenarios",
            json={
                "asset_id": "IC-001",
                "scenario": "safety_critical_case",
                "severity": 0.6,
                "duration_ticks": 100,
                "seed": 31,
            },
        )
        assert result.status_code == 200
        scenario_result = result.json()
        assert scenario_result["ground_truth"]["severity"] == 0.6
        assert scenario_result["ground_truth"]["duration_ticks"] == 100
        assert scenario_result["ground_truth"]["seed"] == 31
        assert all(
            "scenario_injection_fallback" not in anomaly["evidence"]
            for anomaly in scenario_result["anomalies"]
        )
        active = client.get("/api/v1/simulator/scenarios").json()
        assert active[0]["asset_id"] == "IC-001"
        assert active[0]["severity"] == 0.6
        assert active[0]["remaining_ticks"] == 100 - active[0]["elapsed_ticks"]
        assert client.delete("/api/v1/simulator/scenarios/IC-001").json()["cleared"] is True
        assert client.get("/api/v1/simulator/scenarios").json() == []
        run = next(
            item
            for item in client.get("/api/v1/simulator/runs").json()
            if item["scenario_id"] == scenario_result["ground_truth"]["scenario_id"]
        )
        assert run["scenario"] == "safety_critical_case"
        assert run["status"] == "cleared"
        assert run["scenario_id"] == scenario_result["ground_truth"]["scenario_id"]
        assert isinstance(run["detected"], bool)
        assert isinstance(run["missed"], bool)
        assert run["detection_latency_seconds"] is None or run["detection_latency_seconds"] >= 0
        assert isinstance(run["false_positive_count"], int)

        demo = client.post("/api/v1/simulator/demo-workflow", json={"asset_id": "IC-001"})
        assert demo.status_code == 200
        package = demo.json()["approval_package"]
        assert demo.json()["event_source"] == "workflow_demo_injection"
        assert demo.json()["status"] == "pending_approval"
        assert "safety_critical" in package["reasons_for_hitl"]
        assert all(
            anomaly.anomaly_id != demo.json()["correlation_id"]
            for anomaly in runtime.pipeline.anomalies
        )

        correlation_id = demo.json()["correlation_id"]
        missing_reason = client.post(
            f"/api/v1/approvals/{correlation_id}/decision",
            json={
                "correlation_id": correlation_id,
                "decision": "reject",
                "approver": "ignored",
            },
        )
        assert missing_reason.status_code == 422

        approved = client.post(
            f"/api/v1/approvals/{correlation_id}/decision",
            headers={"X-Approver-Id": "technician-supervisor"},
            json={
                "correlation_id": correlation_id,
                "decision": "approve",
                "approver": "untrusted-body-value",
            },
        )
        assert approved.status_code == 200
        assert approved.json()["approval"]["approver"] == "technician-supervisor"
        assert client.get("/api/v1/audit/verify").json()["ok"] is True


def test_sse_stream_emits_named_event_and_event_data() -> None:
    with TestClient(app) as client:
        runtime = app.state.runtime
        while not runtime.pipeline.events.empty():
            runtime.pipeline.events.get_nowait()
        while not runtime.workflow.events.empty():
            runtime.workflow.events.get_nowait()
        runtime.pipeline.pause()
        runtime.workflow.events.put_nowait({"type": "health", "data": {"status": "ok"}})
        try:
            with client.stream("GET", "/api/v1/stream") as response:
                assert response.status_code == 200
                lines = iter(response.iter_lines())
                assert next(lines) == "event: health"
                assert next(lines).startswith('data: {"status": "ok"}')
        finally:
            runtime.pipeline.resume()


def test_sensor_fault_scenarios_exercise_normalizer_and_keep_truth_separate() -> None:
    with TestClient(app) as client:
        runtime = app.state.runtime
        client.post("/api/v1/simulator/reset")
        dropout = client.post(
            "/api/v1/simulator/scenarios",
            json={
                "asset_id": "WD-001",
                "scenario": "sensor_dropout",
                "duration_ticks": 100,
                "measurement_type": "temperature",
                "seed": 21,
            },
        ).json()
        dropout_id = dropout["ground_truth"]["scenario_id"]
        dropout_readings = [
            reading for reading in runtime.pipeline.readings if reading.scenario_id == dropout_id
        ]
        assert dropout_readings
        assert all(reading.measurement_type.value != "temperature" for reading in dropout_readings)
        assert all(reading.scenario_id == dropout_id for reading in dropout_readings)
        detected_for_run = [
            anomaly for anomaly in runtime.pipeline.anomalies if anomaly.scenario_id == dropout_id
        ]
        assert all(
            "scenario_id" not in anomaly.evidence["features"] for anomaly in detected_for_run
        )

        client.post("/api/v1/simulator/reset")
        client.post(
            "/api/v1/simulator/scenarios",
            json={
                "asset_id": "WD-001",
                "scenario": "bad_quality",
                "duration_ticks": 100,
                "measurement_type": "current",
                "seed": 21,
            },
        )
        assert runtime.pipeline.normalizer.dropped_bad > 0

        client.post("/api/v1/simulator/reset")
        client.post(
            "/api/v1/simulator/scenarios",
            json={
                "asset_id": "WD-001",
                "scenario": "out_of_order",
                "duration_ticks": 100,
                "measurement_type": "pressure",
                "seed": 21,
            },
        )
        assert runtime.pipeline.normalizer.dropped_out_of_order > 0
