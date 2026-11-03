"""Estimate simulator noise and process parameters from a sensor CSV."""

import argparse
import csv
import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import fmean, pstdev
from typing import Any

REQUIRED_COLUMNS = {
    "timestamp_utc",
    "asset_id",
    "sensor_id",
    "measurement_type",
    "value",
    "load",
}


def _correlation(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_mean = fmean(left)
    right_mean = fmean(right)
    left_centered = [value - left_mean for value in left]
    right_centered = [value - right_mean for value in right]
    denominator = math.sqrt(
        sum(value * value for value in left_centered)
        * sum(value * value for value in right_centered)
    )
    return (
        sum(a * b for a, b in zip(left_centered, right_centered, strict=True)) / denominator
        if denominator
        else None
    )


def _fit_load_residuals(rows: list[dict[str, Any]]) -> tuple[list[float], float | None]:
    loads = [row["load"] for row in rows]
    values = [row["value"] for row in rows]
    if len(values) < 3:
        return [], None
    load_mean = fmean(loads)
    value_mean = fmean(values)
    variance = sum((load - load_mean) ** 2 for load in loads)
    slope = (
        sum(
            (load - load_mean) * (value - value_mean)
            for load, value in zip(loads, values, strict=True)
        )
        / variance
        if variance
        else 0.0
    )
    intercept = value_mean - slope * load_mean
    residuals = [
        value - (intercept + slope * load) for load, value in zip(loads, values, strict=True)
    ]
    return residuals, slope


def _estimate_thermal_time_constant(rows: list[dict[str, Any]]) -> float | None:
    candidates: list[float] = []
    rows = sorted(rows, key=lambda row: row["timestamp_utc"])
    for start_index in range(1, len(rows) - 2):
        before = rows[start_index - 1]
        start = rows[start_index]
        if abs(start["load"] - before["load"]) < 0.2:
            continue
        segment_end = start_index + 1
        while segment_end < len(rows) and abs(rows[segment_end]["load"] - start["load"]) < 0.2:
            segment_end += 1
        segment = rows[start_index:segment_end]
        if len(segment) < 3:
            continue
        initial = start["value"]
        steady = segment[-1]["value"]
        delta = steady - initial
        if abs(delta) < 1e-9:
            continue
        target = initial + 0.6321205588 * delta
        crossing = next((row for row in segment if (row["value"] - target) * delta >= 0), None)
        if crossing is None:
            continue
        seconds = (crossing["timestamp_utc"] - start["timestamp_utc"]).total_seconds()
        if seconds > 0:
            candidates.append(seconds)
    return fmean(candidates) if candidates else None


def calibrate(path: Path) -> dict[str, Any]:
    with path.open(newline="", encoding="utf-8-sig") as source:
        reader = csv.DictReader(source)
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"CSV is missing required columns: {', '.join(sorted(missing))}")
        rows = [
            {
                "timestamp_utc": datetime.fromisoformat(
                    item["timestamp_utc"].replace("Z", "+00:00")
                ),
                "asset_id": item["asset_id"],
                "sensor_id": item["sensor_id"],
                "measurement_type": item["measurement_type"],
                "value": float(item["value"]),
                "load": float(item["load"]),
            }
            for item in reader
        ]
    if not rows:
        raise ValueError("CSV contains no telemetry rows")

    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(row["asset_id"], row["sensor_id"], row["measurement_type"])].append(row)

    sensor_estimates = []
    for (asset_id, sensor_id, measurement_type), group in sorted(groups.items()):
        residuals, load_slope = _fit_load_residuals(group)
        sensor_estimates.append(
            {
                "asset_id": asset_id,
                "sensor_id": sensor_id,
                "measurement_type": measurement_type,
                "sample_count": len(group),
                "load_coefficient": load_slope,
                "noise_sigma": pstdev(residuals) if residuals else None,
                "noise_ar1": _correlation(residuals[:-1], residuals[1:]) if residuals else None,
                "thermal_time_constant_seconds": (
                    _estimate_thermal_time_constant(group)
                    if measurement_type == "temperature"
                    else None
                ),
            }
        )

    current_rows = [
        row
        for row in rows
        if row["measurement_type"] == "current" and row["load"] > 0 and row["value"] > 0
    ]
    load_exponent = None
    if len(current_rows) >= 3:
        load_logs = [math.log(row["load"]) for row in current_rows]
        current_logs = [math.log(row["value"]) for row in current_rows]
        load_mean = fmean(load_logs)
        current_mean = fmean(current_logs)
        variance = sum((load - load_mean) ** 2 for load in load_logs)
        if variance:
            load_exponent = (
                sum(
                    (load - load_mean) * (current - current_mean)
                    for load, current in zip(load_logs, current_logs, strict=True)
                )
                / variance
            )
    return {
        "source_csv": str(path),
        "row_count": len(rows),
        "load_current_exponent": load_exponent,
        "sensor_estimates": sensor_estimates,
        "notes": [
            "Estimates are descriptive and require engineering review before simulator adoption.",
            "Thermal time constants are estimated only when the CSV contains clear load steps "
            "and a settling segment.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    result = calibrate(arguments.csv_path)
    rendered = json.dumps(result, indent=2, sort_keys=True)
    if arguments.output:
        arguments.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
