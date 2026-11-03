import json

from scripts.calibrate_simulator import calibrate


def test_calibration_script_reports_noise_and_load_exponent(tmp_path) -> None:
    source = tmp_path / "telemetry.csv"
    source.write_text(
        "timestamp_utc,asset_id,sensor_id,measurement_type,value,load\n"
        "2026-01-01T00:00:00Z,WD-001,current,current,10,0.5\n"
        "2026-01-01T00:00:05Z,WD-001,current,current,12,0.6\n"
        "2026-01-01T00:00:10Z,WD-001,current,current,14,0.7\n"
        "2026-01-01T00:00:15Z,WD-001,current,current,16,0.8\n",
        encoding="utf-8",
    )

    result = calibrate(source)

    assert result["row_count"] == 4
    assert result["load_current_exponent"] is not None
    assert result["sensor_estimates"][0]["noise_sigma"] is not None
    assert json.dumps(result)
