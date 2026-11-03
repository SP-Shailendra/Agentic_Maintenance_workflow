"""Run a bounded healthy simulation; pacing is opt-in and explicitly reported."""

import argparse
import hashlib
import json
import math
import time
from datetime import timedelta
from pathlib import Path

from app.datapulse.simulator import TelemetrySimulator


def validate(days: float = 7, seed: int = 17, paced: bool = False) -> dict:
    simulator = TelemetrySimulator(seed=seed, speed=100)
    ticks = math.ceil(days * 86400 / simulator.tick_seconds)
    digest = hashlib.sha256()
    count = 0
    quality_counts: dict[str, int] = {}
    last_timestamps = {}
    start = time.perf_counter()
    for tick in range(ticks):
        for reading in simulator.generate_tick():
            if not math.isfinite(reading.value):
                raise ValueError("Simulator emitted a non-finite value")
            key = (reading.asset_id, reading.sensor_id)
            if key in last_timestamps and reading.timestamp_utc <= last_timestamps[key]:
                raise ValueError("Healthy default timestamps must increase per sensor")
            last_timestamps[key] = reading.timestamp_utc
            flag = reading.quality_flag.value
            quality_counts[flag] = quality_counts.get(flag, 0) + 1
            digest.update(reading.model_dump_json().encode())
            count += 1
        if paced:
            deadline = start + (tick + 1) * simulator.clock.sleep_seconds
            delay = deadline - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
    return {
        "source": "synthetic; not a detection benchmark or plant validation",
        "master_seed": seed,
        "config_hash": simulator.config_hash,
        "ticks": ticks,
        "readings": count,
        "simulated_duration_seconds": ticks * simulator.tick_seconds,
        "speed_setting": simulator.clock.speed,
        "wall_clock_paced": paced,
        "elapsed_seconds": time.perf_counter() - start,
        "quality_counts": quality_counts,
        "telemetry_sha256": digest.hexdigest(),
        "end_time_utc": (
            simulator.clock.t0 + timedelta(seconds=ticks * simulator.tick_seconds)
        ).isoformat(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=float, default=7)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--paced", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not math.isfinite(args.days) or args.days <= 0:
        parser.error("--days must be finite and positive")
    report = json.dumps(validate(args.days, args.seed, args.paced), indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report + "\n", encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
