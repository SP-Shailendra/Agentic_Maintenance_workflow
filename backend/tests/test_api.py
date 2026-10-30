from fastapi.testclient import TestClient

from app.main import app


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
        result = client.post(
            "/api/v1/simulator/scenarios",
            json={"asset_id": "IC-001", "scenario": "safety_critical_case"},
        )
        assert result.status_code == 200
        approvals = client.get("/api/v1/approvals").json()
        package = next(item for item in approvals if item["asset_id"] == "IC-001")
        assert "safety_critical" in package["reasons_for_hitl"]

        missing_reason = client.post(
            f"/api/v1/approvals/{package['correlation_id']}/decision",
            json={
                "correlation_id": package["correlation_id"],
                "decision": "reject",
                "approver": "ignored",
            },
        )
        assert missing_reason.status_code == 422

        approved = client.post(
            f"/api/v1/approvals/{package['correlation_id']}/decision",
            headers={"X-Approver-Id": "technician-supervisor"},
            json={
                "correlation_id": package["correlation_id"],
                "decision": "approve",
                "approver": "untrusted-body-value",
            },
        )
        assert approved.status_code == 200
        assert approved.json()["approval"]["approver"] == "technician-supervisor"
        assert client.get("/api/v1/audit/verify").json()["ok"] is True