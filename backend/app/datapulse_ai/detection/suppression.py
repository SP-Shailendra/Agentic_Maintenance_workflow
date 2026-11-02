"""L3 quiet-period and duplicate-window suppression for noisy alerts."""

from datetime import datetime, timedelta


class AlertSuppressor:
    def __init__(self, quiet_minutes: int = 5, dedup_minutes: int = 15) -> None:
        self.quiet_period = timedelta(minutes=quiet_minutes)
        self.dedup_window = timedelta(minutes=dedup_minutes)
        self._last_seen: dict[tuple[str, str], datetime] = {}
        self._last_emitted: dict[tuple[str, str], datetime] = {}
        self.counts: dict[str, int] = {"quiet_period": 0, "duplicate_window": 0}

    def should_suppress(
        self,
        asset_id: str,
        anomaly_type: str,
        timestamp: datetime,
    ) -> tuple[bool, str | None]:
        key = (asset_id, anomaly_type)
        last_seen = self._last_seen.get(key)
        self._last_seen[key] = timestamp
        if last_seen and timestamp - last_seen < self.dedup_window:
            self.counts["duplicate_window"] += 1
            return True, "duplicate_window"
        last_emitted = self._last_emitted.get(key)
        if last_emitted and timestamp - last_emitted < self.quiet_period:
            self.counts["quiet_period"] += 1
            return True, "quiet_period"
        self._last_emitted[key] = timestamp
        return False, None
