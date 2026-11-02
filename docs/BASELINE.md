# Detection Baseline (Phase 0)

This is the reproducible before-picture for Phase 0. All runs use synthetic simulator data; these figures are not real-plant performance claims.

## Reproduction

```powershell
Push-Location backend
python -m scripts.baseline_report
Pop-Location
```

Seed `17`, `300` ticks, `5.0` simulated seconds per tick, five seeded assets.
Python `3.11.9`; scikit-learn `not installed`.

## Prompt-Reported Reference vs. Local Reproduction

| Run | Prompt-reported | Locally reproduced |
| --- | --- | --- |
| Healthy, 300 ticks | 20 anomalies, 1,248 suppressed | 16 anomalies, 1006 suppressed |
| WD-001 bearing wear, 300 ticks | Events on all five assets at tick 0 | 14 total anomalies; target detected: True; target latency: 0 ticks; cross-asset events: 12 |

The prompt-reported figures are preserved as operator-provided reference values; the local reproduction is not forced to match them. Differences must be explained by seed, dependency availability, and simulator/runtime changes before treating them as comparable.

## Reproduced Metrics

| Metric | Healthy | WD-001 bearing wear |
| --- | ---: | ---: |
| Detector events | 16 | 14 |
| Suppressed alerts | 1006 | 1237 |
| Startup events before tick 10 | 9 | 10 |
| Events per asset-hour | 7.68 | N/A |
| Target fault detected | N/A | True |
| Target detection latency (ticks) | N/A | 0 |
| Cross-asset events during fault | N/A | 12 |

### Events by Asset/Type

Healthy:
```json
{
  "IC-001/bearing_wear": 1,
  "IC-001/electrical_load": 1,
  "IC-001/overheat": 1,
  "IC-001/pressure_drop": 1,
  "IC-002/bearing_wear": 1,
  "IC-002/electrical_load": 1,
  "IC-002/overheat": 1,
  "TG-001/bearing_wear": 1,
  "TG-001/electrical_load": 1,
  "WD-001/bearing_wear": 1,
  "WD-001/electrical_load": 1,
  "WD-001/overheat": 1,
  "WD-001/pressure_drop": 1,
  "WD-002/bearing_wear": 1,
  "WD-002/electrical_load": 1,
  "WD-002/overheat": 1
}
```
Fault injection:
```json
{
  "IC-001/bearing_wear": 1,
  "IC-001/electrical_load": 1,
  "IC-001/overheat": 1,
  "IC-001/pressure_drop": 1,
  "IC-002/bearing_wear": 1,
  "IC-002/electrical_load": 1,
  "IC-002/overheat": 1,
  "TG-001/bearing_wear": 1,
  "TG-001/electrical_load": 1,
  "WD-001/bearing_wear": 1,
  "WD-001/electrical_load": 1,
  "WD-002/bearing_wear": 1,
  "WD-002/electrical_load": 1,
  "WD-002/overheat": 1
}
```

## Limitations Observed

The baseline harness supplies a deterministic simulation timestamp per tick and a deterministic event timestamp per detector call. This makes the before-picture repeatable while preserving the code's known wall-clock suppression behavior.
The isolation-forest detector is marked available only when scikit-learn is installed; a report with it unavailable does not represent the full declared runtime dependency set.
Healthy detector events are false-alert candidates. Cross-asset events during a single-asset fault are not attributed to the injected fault. The benchmark script does not tune thresholds against these cases.

## Strict Expected-Failure Regression Tests

These tests encode known Phase 0 detector defects and use `xfail(strict=True)` so an unexpected pass requires removing the marker:

- `test_healthy_300_ticks_have_no_post_warmup_anomalies`
- `test_spc_baseline_isolated_between_assets_of_same_class`
- `test_reseeding_one_asset_does_not_change_other_asset_readings`
