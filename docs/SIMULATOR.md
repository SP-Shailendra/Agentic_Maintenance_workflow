# Simulator

The simulator is synthetic and for controlled demonstrations, software testing, and replay experiments only. It is not a digital twin or a validated model of any real asset.

## Configuration

- `data/simulator/profiles/default.yaml` contains the master seed, tick cadence, operating cycle, load source, asset-class baselines, and per-asset scaling.
- `data/simulator/scenarios/default.yaml` contains composable machine-fault effects and scenario sensor-fault labels.
- `data/simulator/sensors/default.yaml` contains per-measurement sampling, timestamp jitter, gain/offset, quantization, lag, noise scale, and AR(1) noise.
- Pydantic validates all three documents when loaded. `config_hash` is a SHA-256 digest of the canonical merged configuration; scenario runs include it and the master seed.

## Defaults and Rationale

The numeric values below are placeholders for synthetic behavior. No site historian, OEM datasheet, calibration record, or public dataset has yet been fitted to these values. The `PLACEHOLDER` label is intentional and should remain until an engineer supplies evidence.

| Parameter | Default | Rationale / source status |
| --- | --- | --- |
| Tick interval | 5 seconds | `PLACEHOLDER`: fast enough for a readable demo, not a sensor-cadence claim. |
| Operating cycle | 120 ticks | `PLACEHOLDER`: a ten-minute demonstration cycle at the default tick interval. |
| Ambient temperature | 22 C | `PLACEHOLDER`: generic indoor ambient, not a site design condition. |
| Thermal time constants | 900, 1,200, and 1,800 seconds by class | `PLACEHOLDER`: broad illustrative time scales; calibrate from a measured load-step response. |
| Baseline vibration, temperature, current, and pressure | `profiles/default.yaml` | `PLACEHOLDER`: synthetic starting points carried forward from the original demo. |
| Gaussian noise fraction and floor | 1.2% of baseline, minimum 0.02 units | `PLACEHOLDER`: not fitted to a sensor datasheet or historian. |
| Sensor AR(1) coefficients | Per-sensor values in `sensors/default.yaml` | `PLACEHOLDER`: chosen to exercise colored-noise handling; calibrate from residual autocorrelation. |
| Sensor jitter, quantization, lag | Per-sensor values in `sensors/default.yaml` | `PLACEHOLDER`: illustrative test values, not instrument specifications. |
| Per-asset scale factors | `profiles/default.yaml` | `PLACEHOLDER`: deterministic individuality for simulation, not observed fleet variation. |
| Fault drift coefficients | `scenarios/default.yaml` | `PLACEHOLDER`: signs and ordering are illustrative; severity/duration are test controls. |
| Curve rates, shape, onset and burst periods | `ScenarioProfile` and scenario YAML | `PLACEHOLDER`: synthetic trajectory families, not fitted hazard or lifetime distributions. |
| Gateway delay, jitter, loss, duplication and outage | `transport` in profile YAML | Disabled by default; `PLACEHOLDER` buffer capacity bounds memory during an injected outage. Delays use whole simulation ticks. |
| Accelerometer bandwidth, shaft speed and bearing geometry | `vibration` in profile YAML | `PLACEHOLDER`: illustrative geometry and resonance, not an installed bearing or sensor specification. |
| Sensor drift and swapped measurement | `SensorProfile` | Drift defaults to zero; unspecified channel swaps select another configured measurement. Neither is a calibrated instrument model. |

ISO 20816 vibration zones and OEM ratings are not used to certify these values. They should only be introduced after asset-specific measurement units, mounting, operating speed, and sensor bandwidth are known.

## Clock, Seeds, and Replay

`SimClock` owns simulated timestamps and supports 1x, 10x, 100x, and max-speed operation. A master seed is expanded with NumPy `SeedSequence.spawn()` into independent asset/sensor/noise generators. Injecting or reseeding one asset does not alter another asset's random stream. Identical seed, merged config, and controls produce byte-identical telemetry values and timestamps.

The current API exposes config inspection/replacement and YAML reload, speed changes, scenario runs, run detail/replay, asset parameter changes with one-step undo, sensor-fault injection, and CSV/Parquet/NDJSON telemetry export. Config PUT and asset tweaks are written to the YAML files and audit-logged; reload re-reads those files. Any config replacement rebuilds the in-memory pipeline, so current readings and detector history are reset. Run replay reapplies controls to the current pipeline; it is not yet a persisted initial-state snapshot replay.

## Sensor and Machine Faults

Machine faults are scenario profiles and alter process readings; sensor faults are separate profiles and alter sampled output/quality. Available configured effects include dropout, bad quality, out-of-order time, spikes, stuck-at/flat-line, bias step, noise increase, unit flip, and swapped-channel values/units with uncertain quality. Machine profiles include bearing wear, overheat, pressure drop, intermittent/recovering faults, imbalance, misalignment, fouling, insulation degradation, refrigerant loss, blocked filter, capacitor degradation, sudden trip, and compound fault. Curves support linear, exponential, stepwise, sigmoid, bursty and Weibull cumulative-hazard shapes. Named components compose effects; validation rejects missing components and cycles. These are synthetic trajectory families, not validated physics or fitted survival models. Only one scenario is active per asset, so separate sensor and machine injection cannot yet overlap on the same asset.

Temperature follows a first-order lag toward an ambient/load-dependent target. Current has a startup inrush multiplier and the process state supports stopped, starting, running, idle, and stopping. CSV replay and schedule load sources are supported by the loader; no example replay CSV is bundled.

Scalar vibration RMS is sampled at low rate. No FFT/envelope-spectrum feature is computed from it. The separate `GET /api/v1/simulator/assets/{id}/vibration?severity=...` endpoint synthesizes raw acceleration with configured shaft harmonics, geometry-derived BPFO/BPFI impulses, modulation and broadband noise. SciPy supplies convolution, Hilbert envelope and kurtosis; spectra use the configured raw sample rate. Raw acceleration RMS is not substituted for scalar velocity RMS because their units differ. Raw-window generation and Parquet encoding run in worker threads.

Transport applies independent seeded latency/jitter, loss, duplicates, delayed out-of-order delivery, clock skew and gateway outages. Its bounded store-and-forward buffer releases due readings after recovery; overflow increments a drop counter. Sampling timestamps remain measurement timestamps, not delivery timestamps. Sensor offset drift is expressed per simulated day.

## Validation Evidence

The golden digest test locks the default telemetry bytes. Focused tests cover seed isolation, autocorrelation, thermal step response, healthy statistics across seeds, bearing signature ordering, composed curves, outage bursts and raw bearing spectra.

Generate a long-horizon report with:

```powershell
uv run --locked --directory backend python -m scripts.validate_simulator --days 7 --seed 17 --output ../docs/SIMULATOR_ACCEPTANCE.json
```

The checked-in [acceptance report](SIMULATOR_ACCEPTANCE.json) records the generated reading count, config hash, digest, measured runtime and pacing mode. This run sets speed to 100 but bypasses wall-clock sleeps. It validates finite healthy telemetry and per-sensor timestamp order, not detection false-alert rates. Use `--paced` for actual 100x wall-clock pacing; that long-running acceptance has not been executed.

## Calibration

The CSV calibration utility expects `timestamp_utc,asset_id,sensor_id,measurement_type,value,load`; temperature time-constant estimates additionally need clear load steps and settling intervals. It reports per-sensor residual sigma and AR(1), a load-current exponent, and an estimated thermal time constant when the data supports one:

```powershell
Push-Location backend
uv run --locked python -m scripts.calibrate_simulator path\to\historian.csv --output calibration.json
Pop-Location
```

Calibration output is an estimate, not an automatic config update. Review units, filtering, operating regimes, and step selection before copying any value into the YAML profiles.
