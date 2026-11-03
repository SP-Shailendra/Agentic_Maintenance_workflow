# Detection Baseline and Phase 1 Results

This report preserves the Phase 0 before-picture and compares it with the Phase 1 detector changes. All runs use synthetic simulator data; these figures are not real-plant performance claims.

## Reproduction

```powershell
Push-Location backend
python -m scripts.baseline_report
Pop-Location
```

Seed `17`, `300` ticks, `5.0` simulated seconds per tick, five seeded assets.
Python `3.11.9`; scikit-learn `not installed`.

## Reference and Reproduction

| Run | Prompt-reported | Phase 0 local | Phase 1 local |
| --- | --- | --- | --- |
| Healthy, 300 ticks | 20 anomalies, 1,248 suppressed | 16 anomalies, 1006 suppressed | 0 anomalies, 0 suppressed |
| WD-001 bearing wear, 300 ticks | Events on all five assets at tick 0 | 14 total anomalies; target latency: 0 ticks; cross-asset events: 12 | 1 total anomalies; target detected: True; target latency: 3 ticks; cross-asset events: 0 |

The prompt-reported figures are preserved as operator-provided reference values; the local reproduction is not forced to match them. Differences must be explained by seed, dependency availability, and simulator/runtime changes before treating them as comparable.

## Phase 1 Changes

- Simulator noise uses independent per-asset random streams; scenario reseeding no longer perturbs other assets.
- SPC histories and CUSUM state are keyed per asset and measurement, with phase-conditioned residuals trained from eight healthy operating cycles.
- SPC uses a five-sigma point limit and a 30-unit CUSUM limit, calibrated against the fixed-seed synthetic benchmark.
- Optional Isolation Forest scores are calibrated against the training-score tail and healthy input range rather than mapping the training minimum to maximum risk.

## Reproduced Metrics

| Metric | Healthy | WD-001 bearing wear |
| --- | ---: | ---: |
| Detector events | 0 | 1 |
| Suppressed alerts | 0 | 296 |
| Startup events before tick 10 | 0 | 1 |
| Events per asset-hour | 0.0 | N/A |
| Target fault detected | N/A | True |
| Target detection latency (ticks) | N/A | 3 |
| Cross-asset events during fault | N/A | 0 |

### Events by Asset/Type

Healthy:
```json
{}
```
Fault injection:
```json
{
  "WD-001/bearing_wear": 1
}
```

## Limitations Observed

The baseline harness supplies a deterministic simulation timestamp per tick and a deterministic event timestamp per detector call. This makes the before-picture repeatable while preserving the code's known wall-clock suppression behavior.
The isolation-forest detector is marked available only when scikit-learn is installed; a report with it unavailable does not represent the full declared runtime dependency set.
Healthy detector events are false-alert candidates. Cross-asset events during a single-asset fault are not attributed to the injected fault. Phase 1 threshold calibration is synthetic and fixed-seed; independent seeds and real operating data are needed to assess generalization.

## Phase 1 Regression Coverage

The former strict expected-failure checks are now active passing regressions:

- `test_healthy_300_ticks_have_no_post_warmup_anomalies`
- `test_spc_baseline_isolated_between_assets_of_same_class`
- `test_reseeding_one_asset_does_not_change_other_asset_readings`
