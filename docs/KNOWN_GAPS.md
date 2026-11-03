# Known Gaps

This list records requested work that is not complete. Numeric claims remain synthetic unless a script and data source are stated.

## WP2 Simulator

- Defaults are explicitly `PLACEHOLDER`; no OEM/datasheet/site historian calibration has been completed.
- Operating states, ambient thermal lag, per-asset scaling, AR(1) noise, sensor jitter/lag/quantization/drift, composable degradation curves, config hash and SimClock speed are implemented. Statistical tests cover autocorrelation, thermal response, seed stability and bearing ordering, but no real-asset calibration evidence is available.
- Safety/unclassified scenario profiles are no longer tied to asset IDs.
- Sensor faults are injectable through the dedicated API and scenario profiles. Transport loss/delay/duplication/out-of-order/skew, bounded gateway store-and-forward and actual channel-value swaps are implemented. Sensor and machine injections still share one active scenario slot per asset.
- Scalar-RMS FFT was removed. A separate raw acceleration API supplies configured bearing impulses, envelope spectra, kurtosis and crest factor. Raw acceleration features are not yet integrated into pipeline detection; they are not interchangeable with velocity RMS.
- Config GET/PUT/reload, speed, run start/detail/replay, audited parameter update/undo, and CSV/Parquet/NDJSON export exist. Config changes rebuild the in-memory pipeline and reset its history; replay currently reapplies controls rather than restoring a saved initial-state snapshot.
- The seven-day simulator-only run is recorded in `SIMULATOR_ACCEPTANCE.json`. It is explicitly unpaced despite the 100x speed setting. A wall-clock-paced 100x run and a seven-day full-detector false-alert evaluation remain unexecuted.
