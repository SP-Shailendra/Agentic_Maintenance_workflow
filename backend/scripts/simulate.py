"""Run a short deterministic simulator burst and summarize detected events."""

import asyncio

from app.datapulse.pipeline import PipelineRunner


async def main() -> None:
    runner = PipelineRunner()
    runner.simulator.tick_seconds = 0
    runner.simulator.inject("WD-001", "bearing_wear")
    for _ in range(20):
        await runner.process_tick()
    for anomaly in runner.anomalies:
        print(
            f"{anomaly.anomaly_id} asset={anomaly.asset_id} "
            f"type={anomaly.anomaly_type} severity={anomaly.severity:.2f}"
        )
    print(f"readings={len(runner.readings)} suppressed={len(runner.suppressed)}")


if __name__ == "__main__":
    asyncio.run(main())
