# Pour-Over

**A measurement-constrained physics model of V60 coffee brewing**

A coupled reduced-order model for studying how pouring becomes outflow, solute release, and cup temperature. The model combines porous-media hydraulics, measured particle-size distributions, and multi-node heat balances so that brewing curves and their underlying physical assumptions can be tested together.

[Model and assumptions](docs/model.md) · [Reproducibility and calibration](docs/reproducibility.md) · [Literature map](docs/literature_map.md)

## Research scope

Pour-over brewing couples water retention, unsaturated drainage, diffusion within coffee particles, and heat exchange with the equipment. This project represents those processes as coupled ordinary differential equations. Measured recipes and particle-size distributions provide the inputs; outputs include volume, flow rate, retained water, temperature, total dissolved solids (TDS), and extraction yield (EY).

The **reduced-order porous-media model** describes a complete brew through explicit mechanisms and a small set of closure parameters. It does not resolve the three-dimensional flow field inside the bed. Its intended uses are mechanism analysis, comparison with measurements, and exploration near calibrated conditions. Prediction across recipes still requires independent experimental validation.

## Model architecture

| Module | Physical description | Measurement constraints |
|---|---|---|
| Hydraulics | Darcy flow, capillary retention, unsaturated relative permeability, and separate throat and deposition clogging | Pour and outflow curves, stop time, bed height |
| Extraction | Broken-shell and particle-core release in each measured PSD bin, coupled to layered solute transport | Particle-size and shape distributions, final TDS |
| Heat transfer | Heat exchange among the slurry, dripper, server, and surroundings | Equipment mass, water temperature, server temperature series or a single cup reading |

Temperature affects flow through viscosity and extraction through diffusivity and solubility. Calibration proceeds through hydraulics, heat transfer, and extraction in stages. Measured inputs remain fixed to limit compensation for errors in one module by parameters in another.

See the model documentation for [release laws](docs/model.md#release-laws), the [particle-size distribution contract](docs/model.md#particle-size-distribution), and fixed assumptions.

## Comparison with a measured brew

The reference brew uses 20 g of light-roast coffee at Kinu setting 29 (`kinu29/4:12`). Results below come from the current [calibration summary](data/kinu_29_light/4:12/kinu29_light_20g_flow_fit_summary.csv).

### Cup-level results

| Quantity | Measured | Model | Difference |
|---|---:|---:|---|
| Outflow stop time | 120.9 s | 121.1 s | About 0.2 s later |
| Final cup temperature | 75.0 °C | 74.6 °C | About 0.4 °C lower |
| Coffee concentration (TDS) | 11.56 g/L | 11.60 g/L | About 0.04 g/L higher |

Stop time is defined by the server liquid level approaching a plateau. Cup temperatures are compared at the same reading time (132 s). TDS is the mass of dissolved solids per litre of coffee; the model comparison uses the measured final beverage volume.

**These results follow calibration to this brew.** Each case has one TDS observation and one adjustable extraction parameter. A small concentration difference therefore does not establish predictive accuracy for a new recipe.

### Agreement throughout the brew

Similar final values can conceal errors along the way. Outflow and temperature are also checked over time:

| Check | Reference result | Interpretation |
|---|---|---|
| Outflow curve mismatch | RMSE 2.65 mL | Overall mismatch at fitted observation times, not the largest error |
| Server temperature mismatch | RMSE 0.93 °C | Only 6 readings that pass observation screening, with at least 150 mL in the server |
| Known timing discrepancy | Second-pour outflow arrives about 2–4 s early | A small overall mismatch still leaves a local timing error unresolved |

RMSE is the root mean square error, a summary of mismatch across observation times. It is not a bound on the error at every instant.

### Coverage of the checks

Three brews have video-based measurements. The reference Kinu 29 brew and the Kinu 28 brew pass the specified checks; the Kinu 27 brew retains a systematic pattern in its residuals. A fourth, hand-logged brew fails the checks and has suspected bias in its outflow readings.

Each case is calibrated separately, and the full suite does not yet pass. The number of passing cases is not a predictive accuracy rate for new brews. See the [benchmark results, metric definitions, and diagnostic figures](docs/reproducibility.md#calibration-report-and-diagnostics) for details.

## Quick start

Requires Python ≥ 3.13 and [uv](https://docs.astral.sh/uv/). Install dependencies from the project root:

```bash
uv sync
```

Simulate 180 seconds with the built-in light-roast defaults:

```python
from pour_over import V60Params, RoastProfile, PourProtocol, simulate_brew

params = V60Params.for_roast(RoastProfile.LIGHT)
results = simulate_brew(params, PourProtocol.standard_v60(), t_end=180)
print(f"TDS = {results['TDS_gl'][-1]:.1f} g/L, EY = {results['EY_pct'][-1]:.1f}%")
```

This example demonstrates the API. For replaying the calibrated reference brew, fitting your own measurements, and running the benchmark, see [Reproducibility and calibration](docs/reproducibility.md).

## Scope and limitations

- **Generalization:** New pour schedules and water temperatures have not been validated against new measured brews. Transferring extraction parameters between cases produces TDS errors of up to about 2.7 g/L.
- **Particle-size measurements:** The absolute PSD scale retains approximately ±45% systematic uncertainty. Repeat scans at one setting can differ more than neighbouring settings; the current data cannot resolve small grind changes. Permeability is calibrated per case.
- **Timing and thermal structure:** Second-pour outflow arrives about 2–4 s early. Early heat coupling below about 150 mL in the server is insufficiently represented, and those temperature readings are excluded from fitting.
- **Parameter interpretation:** `τ_wet` should not be treated as a directly measured wetting time. Reported confidence intervals hold the other parameters fixed and underestimate joint uncertainty.

See [Model applicability](docs/model.md#model-applicability) for the full assumptions and diagnostics.

## Documentation and data

| Resource | Contents |
|---|---|
| [Model and assumptions](docs/model.md) | Equations, PSD contract, parameter roles, and limitations |
| [Reproducibility and calibration](docs/reproducibility.md) | Simulation, data preparation, fitting, benchmarks, and code organization |
| [Measurement workflow](tools/video/README.md) | Frame-by-frame video readings and observation construction |
| [Literature map](docs/literature_map.md) | Sources and evidence strength for each closure |
| [Reference case data](data/kinu_29_light/4:12/) | Measured curves, PSD, calibration summaries, and diagnostic figures |

Model development, rejected mechanisms, and experiments are recorded in the [experiment log](docs/experiment_log.md); its `[BASELINE]` section defines the current reference. Raw videos and photographs are not version-controlled. Traceable readings are retained under `data/<case>/video/`.

## License

[MIT License](LICENSE)
