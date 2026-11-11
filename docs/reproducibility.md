# Reproducibility and calibration

[Project overview](../README.md) · [Model and assumptions](model.md)

Run all commands from the project root. Python requirements and dependencies are defined in [pyproject.toml](../pyproject.toml), with versions recorded in `uv.lock`. The [experiment log's `[BASELINE]`](experiment_log.md#baseline-current) identifies the current calibration and its artifacts.

## Installation and checks

```bash
uv sync --locked
uv run python -m compileall pour_over
uv run python -m unittest discover -s tests
```

Tests cover conservation, PSD invariants, fitting objectives, and observation lag. Passing unit tests does not imply that the four-case benchmark passes.

## Simulation and replay

Built-in roast defaults provide an introduction to the API; the overview example uses a 180 s horizon. To replay the current reference case with its calibrated parameters and measured pour schedule:

```python
from pour_over import simulate_brew
from pour_over.showcase_state import latest_calibrated_params, latest_protocol

params = latest_calibrated_params()
protocol = latest_protocol()
results = simulate_brew(params, protocol, t_end=180)
```

`results` includes outflow volume `v_out_ml`, slurry temperature `T_C`, concentration `TDS_gl`, extraction yield `EY_pct`, fast/slow contributions, and per-bin solute masses. Simulated `TDS_gl` and the calibration report's TDS comparison use different volume denominators: the latter uses measured final beverage volume. They are not interchangeable error metrics.

### Showcase figures and CLI

```bash
uv run python -m pour_over
```

This loads the calibrated state, generates `v60_simulation.png`, `v60_tds.png`, `v60_grind.png`, and `v60_thermal.png`, runs a grind search, and refits the reference case, writing its summary and diagnostic figures. The showcase currently uses an extended `t_end=500` horizon; use the API example above for 180 s.

**Refitting overwrites the corresponding calibration artifacts.** To inspect existing results, use the [calibration report and diagnostics](#calibration-report-and-diagnostics). To replay without refitting, use `latest_calibrated_params()`.

## Preparing your measurements

Use a separate `data/<case>/` directory for each brew. The [reference case directory](../data/kinu_29_light/4:12/) provides complete examples.

| File | Contents |
|---|---|
| `*_flow_profile.csv` or `*_flow_profile_video.csv` | Time-series readings with recipe metadata repeated on every row |
| `*_psd_bins.csv` | Model-ready PSD converted from raw particle exports |
| `*_psd_summary.csv` | PSD summaries and measurement-scale diagnostics |

Main flow-profile columns are `time_s`, `poured_weight_g`, `drained_volume_ml`, and `use_for_fit`. Metadata includes `dose_g`, `bed_height_cm`, `brew_temp_C`, `ambient_temp_C`, `dripper_mass_g`, and `final_tds_pct`. Use the complete example CSV and the loading rules in [measured_io.py](../pour_over/measured_io.py) as the contract; this list is not a minimal schema.

Video profiles take precedence when available. Hand-logged outflow readings may be biased; cases without video retain the `drained_log_bias_suspected` quality flag. Frame readings, temperature observations, and profile construction are documented in the [video workflow](../tools/video/README.md).

PSD input comes from raw exports of the [coffeegrindsize fork](https://github.com/latteine1217/coffeegrindsize). Inspect conversion options with:

```bash
uv run python -m pour_over.psd --help
```

See [Particle-size distribution](model.md#particle-size-distribution) for field and scale definitions. `PIXEL_SCALE` is in px/mm. Missing or inconsistent scale metadata must be resolved at the source; do not guess units or rescale using `D10`.

## Calibration workflow

1. **Preprocessing:** Load through `_prepare_measured_case(preprocess=True)`. Pour-rate reconstruction, running-max corrections, and reading-time uncertainty propagation are applied in memory. Raw CSVs remain unchanged.
2. **Hydraulics:** Fit `k`, Corey-type `n`, and `τ_wet`. Stages 1/2/4 minimize only `chi2_hydraulic` to avoid absorbing errors from uncalibrated thermal and extraction parameters.
3. **Heat transfer:** Fit `U` for cases with an accepted video temperature series, or server cooling for cases with only one cup temperature. Stage 5 uses total χ².
4. **Extraction:** After hydraulics converges, constrain `τ_tort` with final TDS. Stage 7 uses total χ². The comparison divides dissolved mass by measured final beverage volume, taken from the last `use_for_fit` row before dripper removal.

Fitting uses bounded least squares with two LHS starts and a sibling warm-start. `k_beta` is fixed to the PSD-derived value, outlet lag to `0.5 s`, and `max_EY` to its roast prior. ODE integration is piecewise, with tolerances no looser than `rtol=1e-7` and `atol=1e-9`.

### Generating fit artifacts for your case

After preparing the data, replace these paths with your own:

```python
from pour_over.fitting import generate_measured_flow_fit_artifacts

params, info = generate_measured_flow_fit_artifacts(
    csv_path="data/my_brew/my_brew_flow_profile.csv",
    plot_path="data/my_brew/my_brew_flow_fit.png",
    summary_path="data/my_brew/my_brew_flow_fit_summary.csv",
)
```

Outputs include a summary CSV, measured-versus-model comparison, residual time series, and retention comparison. Video temperature readings also produce a thermal video check. The summary contains parameters, available conditional confidence intervals, χ² components, quality flags, and `preprocess_corrections`. An unavailable interval does not mean that a parameter is precisely determined.

Inspect `profile_source`, `profile_path`, `fit_live_param_names`, active parameter bounds, and `preprocess_corrections`. The reference case currently has only `t=0s reading_time_sigma_s 1->0.1 (video frame-resolved readings)`. Unexpected corrections require checking the data and code.

## Calibration report and diagnostics

The overview presents measured and model values side by side for the reference brew. Values come from the [kinu29/4:12 summary](../data/kinu_29_light/4:12/kinu29_light_20g_flow_fit_summary.csv). This section supplies field definitions, statistical checks, and diagnostic links.

| Overview item | Summary fields | Comparison conditions |
|---|---|---|
| Outflow stop time | `stop_flow_time_s` / `cup_stop_time_s` | Both use the liquid-level stop operator; this is not dripper removal time |
| Final cup temperature | `final_cup_temp_C` / `mixed_cup_temp_C` | Evaluated at `final_temp_read_time_s = 132 s`; with an accepted temperature series, the single reading is diagnostic, is not counted again in χ², and is not an independent held-out observation |
| TDS | `final_tds_gl_obs` / `tds_pred_measured_denominator` | Model dissolved mass divided by measured final volume; one concentration observation fits one `τ_tort` per case |
| Outflow curve RMSE | `rmse_ml` | Root mean square of volume residuals within the fit mask, not a maximum error or uncertainty bound |
| Server temperature RMSE | `server_series_rmse_C` | Accepted fitted readings: 6 points with at least 150 mL for the reference case; not the full-series diagnostic `thermal_video_server_rmse_C` |

The 2–4 s second-pour lead comes from the [current baseline's timing diagnostics](experiment_log.md#baseline-current), not a conversion of RMSE. The overview rounds values for readability; CSVs retain full precision. Differences are calculated as model minus measured values before rounding.

### Four-case checks

Results below come from the current [benchmark CSV](../data/benchmark_suite_summary.csv). Reduced χ² measures overall mismatch normalized by measurement uncertainty. It must be interpreted alongside residual temporal correlation and the other gates; a small value does not establish correctness at every time or for every mechanism.

| Case | Data source | Reduced χ² | Result and failing checks |
|---|---|---:|---|
| Kinu 29 · 4/12 (reference) | Video | 0.375 | PASS |
| Kinu 27 · 4/12 | Video | 0.387 | FAIL: residual temporal correlation |
| Kinu 28 · 4/20 | Video | 0.513 | PASS |
| Kinu 29 · 4/11 | Hand log | 8.739 | FAIL: reduced χ² and residual temporal correlation; suspected outflow-reading bias |

### Reference diagnostic figures

| Figure | Purpose |
|---|---|
| [Measured versus model](../data/kinu_29_light/4:12/kinu29_light_20g_flow_fit.png) | Compare cumulative outflow, interval flow rates, and residuals to locate local discrepancies such as pour restart |
| [Residual time series](../data/kinu_29_light/4:12/kinu29_light_20g_flow_fit_residuals.png) | Inspect systematic temporal structure in the residuals |
| [Water retention](../data/kinu_29_light/4:12/kinu29_light_20g_flow_fit_retention.png) | Compare bed water retention over time |
| [Video temperature diagnostics](../data/kinu_29_light/4:12/kinu29_light_20g_thermal_video_check.png) | Compare temperatures using the summary's QC, masks, and time-series error fields |

## Benchmark and identifiability

```bash
uv run python -m pour_over benchmark --all-cases
```

The CLI refits the **reference case**, evaluates gates for all four cases using existing summaries, then runs local reference-case identifiability analysis. `--all-cases` expands benchmark evaluation; it does not refit every case. This command updates reference artifacts, the benchmark CSV, and identifiability outputs.

| Gate | Threshold |
|---|---|
| Reduced χ² | ≤ 3.0 |
| Final retention relative error | ≤ 15%, when the observation is positive |
| Standardized residual temporal correlation | Durbin–Watson ≥ 1.0 **or** lag-1 ≤ 0.5 |
| Absolute cup temperature error | ≤ 1.0 °C |
| Accepted server temperature series RMSE | ≤ 2.0 °C |
| Absolute TDS error | ≤ 1.44 g/L |
| Water balance residual | ≤ 0.05 mL |
| Clipping activity fraction | ≤ 1% |

Interpret missing accepted observations using applicability and QC fields. An unevaluated item is not an independent validation pass. CLI completion does not imply successful research validation: inspect individual checks in the [benchmark CSV](../data/benchmark_suite_summary.csv). Two cases currently pass and two fail; the full suite does not pass.

Confidence intervals are conditional slices with other parameters fixed, not full joint intervals. If neither bound is identifiable within a ±2× range, freeze the parameter rather than adding fitting freedom.

New fits, scans, or benchmarks that produce research conclusions require updating the [experiment log](experiment_log.md) and its index under the project protocol. Documentation-only editing does not create a new experiment record.

## Code and data organization

| Location | Responsibility |
|---|---|
| [core.py](../pour_over/core.py), [params.py](../pour_over/params.py), [constant.py](../pour_over/constant.py) | Coupled ODEs, closures, recipes, and physical constants |
| [psd.py](../pour_over/psd.py) | Raw particle measurements to model-ready bins |
| [measured_io.py](../pour_over/measured_io.py), [preprocess.py](../pour_over/preprocess.py) | Measurement loading, fixed observation constants, and auditable preprocessing |
| [observation.py](../pour_over/observation.py) | Outlet lag, server observations, and stop operators |
| [fitting.py](../pour_over/fitting.py), [benchmark.py](../pour_over/benchmark.py), [identifiability.py](../pour_over/identifiability.py) | Staged calibration, gates, and parameter identifiability |
| [showcase_state.py](../pour_over/showcase_state.py), [viz.py](../pour_over/viz.py), [analysis.py](../pour_over/analysis.py) | Loading the calibration baseline, figures, sensitivity, and grind analysis |
| [data/](../data/), [tools/video/](../tools/video/README.md), [tests/](../tests/) | Measurements and calibration artifacts, video workflow, and regression tests |

Raw videos and photographs are not version-controlled. Frame readings and derived data are retained under `data/<case>/video/`.

Version control retains source code, tests, dependency locks, measurement data, calibration artifacts, literature evidence, and the experiment log. Agent execution plans under `docs/superpowers/`, tool caches, and local media stay outside version control. Project instructions in `AGENTS.md` and its import files remain part of the repository; they define the maintenance protocol rather than recording agent sessions.
