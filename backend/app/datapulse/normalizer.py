"""L1 unit normalization, quality handling, and reading deduplication."""

from datetime import datetime

from app.schemas.domain import MeasurementType, QualityFlag, TelemetryReading

CANONICAL_UNITS = {
    MeasurementType.TEMPERATURE: "degC",
    MeasurementType.PRESSURE: "bar",
    MeasurementType.CURRENT: "A",
    MeasurementType.VIBRATION_RMS: "mm/s",
}


class TelemetryNormalizer:
    def __init__(self) -> None:
        self._seen: set[tuple[str, str, str]] = set()
        self._latest: dict[tuple[str, str], datetime] = {}
        self.dropped_bad = 0
        self.dropped_duplicate = 0
        self.dropped_out_of_order = 0

    def normalize(self, reading: TelemetryReading) -> TelemetryReading | None:
        if reading.quality_flag == QualityFlag.BAD:
            self.dropped_bad += 1
            return None
        key = (reading.asset_id, reading.sensor_id, reading.timestamp_utc.isoformat())
        if key in self._seen:
            self.dropped_duplicate += 1
            return None
        series_key = (reading.asset_id, reading.sensor_id)
        latest = self._latest.get(series_key)
        if latest is not None and reading.timestamp_utc < latest:
            self.dropped_out_of_order += 1
            return None
        self._seen.add(key)
        self._latest[series_key] = reading.timestamp_utc
        value = reading.value
        unit = reading.unit
        if reading.measurement_type == MeasurementType.TEMPERATURE and unit == "degF":
            value = (value - 32) * 5 / 9
        elif reading.measurement_type == MeasurementType.PRESSURE and unit == "psi":
            value *= 0.0689476
        elif reading.measurement_type == MeasurementType.VIBRATION_RMS and unit == "in/s":
            value *= 25.4
        return reading.model_copy(
            update={"value": value, "unit": CANONICAL_UNITS[reading.measurement_type]}
        )
