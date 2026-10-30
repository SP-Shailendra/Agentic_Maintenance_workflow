from fastapi.testclient import TestClient

from app.main import app
from app.runtime import runtime


def test_health_system_config_and_seeded_fleet() -> None:
    with TestClient(app) as client:
        assert client.get("/api/v1/health").json()["status"] == "ok"
        config = client.get("/api/v1/system/config").json()
        assert config["guardrails"]["human_approval_always_required"] is True
        assets = client.get("/api/v1/assets").json()
        assert len(assets) == 5
        assert next(asset for asset in assets if asset["asset_id"] == "IC-002")[
            "safety_critical"
        ] is None


def test_scenario_creates_approval_and_records_approver() -> None:
    with TestClient(app) as client:
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
    while not runtime.pipeline.events.empty():
        runtime.pipeline.events.get_nowait()
    while not runtime.workflow.events.empty():
        runtime.workflow.events.get_nowait()
    runtime.pipeline.pause()
    runtime.workflow.events.put_nowait({"type": "health", "data": {"status": "ok"}})
    try:
        with TestClient(app) as client:
            with client.stream("GET", "/api/v1/stream") as response:
                assert response.status_code == 200
                lines = iter(response.iter_lines())
                assert next(lines) == "event: health"
                assert next(lines).startswith("data: {\"status\": \"ok\"}")
    finally:
        runtime.pipeline.resume()


def test_sensor_fault_scenarios_exercise_normalizer_and_keep_truth_separate() -> None:
    with TestClient(app) as client:
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
            reading
            for reading in runtime.pipeline.readings
            if reading.scenario_id == dropout_id
        ]
        assert dropout_readings
        assert all(reading.measurement_type.value != "temperature" for reading in dropout_readings)
        assert all(reading.scenario_id == dropout_id for reading in dropout_readings)
        detected_for_run = [
            anomaly
            for anomaly in runtime.pipeline.anomalies
            if anomaly.scenario_id == dropout_id
        ]
        assert all(
            "scenario_id" not in anomaly.evidence["features"]
            for anomaly in detected_for_run
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