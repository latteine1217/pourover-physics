# Kinu 29 4/12 Measured Case Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 `data/kinu_29_light/4:12` 為第二個 measured case，接入現有 flow/thermal 驗證管線，同時保持 `4:11` 為正式 showcase baseline。

**Architecture:** 先把 `4/12` 原始手抄資料整理成與 `4:11` 相同的結構化 CSV，再將 measured-case 路徑與 PSD 載入邏輯從硬編碼單一路徑改成「預設 baseline + 額外 case 可顯式指定」。`4:11` 的 benchmark、showcase 與 README 參照維持不動，`4:12` 只作為新增的 measured validation case。

**Tech Stack:** Python, uv, pytest, CSV artifacts

---

### Task 1: 補 parser 與 measured-case 路徑測試

**Files:**
- Create: `tests/test_measured_case_registry.py`
- Modify: `pour_over/measured_io.py`
- Modify: `pour_over/showcase_state.py`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

from pour_over.measured_io import load_flow_profile_csv
from pour_over.showcase_state import measured_case_dir


def test_load_flow_profile_allows_missing_final_tds(tmp_path: Path) -> None:
    csv_path = tmp_path / "flow.csv"
    csv_path.write_text(
        "dose_g,roast,grinder,grinder_setting,bed_height_cm,brew_temp_C,ambient_temp_C,final_coffee_temp_C,final_tds_pct,dripper_mass_g,dripper_cp_J_gK,lambda_liquid_dripper,lambda_dripper_ambient,lambda_server_ambient,time_mmss,time_s,poured_weight_g,drained_volume_ml,use_for_fit,phase\n"
        "20,light,Kinu,29,5.3,92.0,23.0,74.0,,123.5,0.88,0.02,0.004,0.0,00:00,0,0,0,1,start\n"
        "20,light,Kinu,29,5.3,92.0,23.0,74.0,,123.5,0.88,0.02,0.004,0.0,00:05,5,30,5,1,flow_stop_visual\n",
        encoding="utf-8",
    )

    prof = load_flow_profile_csv(csv_path)

    assert prof["final_tds_pct"] is None
    assert prof["stop_flow_time_s"] == 5.0


def test_measured_case_dir_accepts_explicit_case_date() -> None:
    case_dir = measured_case_dir("4:12")
    assert case_dir.name == "4:12"
    assert (case_dir / "PSD_export_data.csv").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_measured_case_registry.py -v`
Expected: FAIL because `final_tds_pct` is still treated as required and `measured_case_dir()` does not yet accept a case id.

- [ ] **Step 3: Write minimal implementation**

```python
final_tds_pct = _optional_float(meta, "final_tds_pct")


def measured_case_dir(case_id: str = "4:11") -> Path:
    case_dir = data_dir() / "kinu_29_light" / case_id
    if not case_dir.exists():
        raise FileNotFoundError(f"缺少 measured case 目錄：{case_dir}")
    return case_dir
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_measured_case_registry.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_measured_case_registry.py pour_over/measured_io.py pour_over/showcase_state.py
git commit -m "test: cover optional measured metadata and case lookup"
```

### Task 2: 結構化 4/12 flow/thermal/PSD artifacts

**Files:**
- Create: `data/kinu_29_light/4:12/kinu29_light_20g_flow_profile.csv`
- Create: `data/kinu_29_light/4:12/kinu29_light_20g_thermal_profile.csv`
- Create: `data/kinu_29_light/4:12/kinu29_psd_summary.csv`
- Create: `data/kinu_29_light/4:12/kinu29_psd_bins.csv`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

from pour_over.measured_io import load_flow_profile_csv


def test_kinu_4_12_structured_case_is_loadable() -> None:
    flow_csv = Path("data/kinu_29_light/4:12/kinu29_light_20g_flow_profile.csv")
    prof = load_flow_profile_csv(flow_csv)

    assert prof["t_s"][-1] == 130.0
    assert prof["v_out_ml"][-1] == 310.0
    assert prof["final_tds_pct"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_measured_case_registry.py -v`
Expected: FAIL because `4:12` structured CSV artifacts do not exist yet.

- [ ] **Step 3: Write minimal implementation**

```bash
uv run python -m pour_over.psd \
  --raw-csv data/kinu_29_light/4:12/PSD_export_data.csv \
  --stats-csv data/kinu_29_light/4:12/PSD_export_data_stats.csv \
  --summary-csv data/kinu_29_light/4:12/kinu29_psd_summary.csv \
  --bins-csv data/kinu_29_light/4:12/kinu29_psd_bins.csv
```

並手動建立與 `4:11` schema 相容的 `flow_profile.csv` / `thermal_profile.csv`，保留 `final_tds_pct` 空值、以 `~` 量測值直接寫入 `estimated_server_volume_ml`。

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_measured_case_registry.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add data/kinu_29_light/4:12
git commit -m "data: add structured measured artifacts for kinu29 4-12"
```

### Task 3: 接入多 measured case 分析入口

**Files:**
- Modify: `pour_over/benchmark.py`
- Modify: `pour_over/analysis.py`
- Modify: `README.md`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

from pour_over.benchmark import _load_measured_benchmark_state


def test_load_measured_benchmark_state_uses_case_local_psd() -> None:
    flow_csv = Path("data/kinu_29_light/4:12/kinu29_light_20g_flow_profile.csv")
    summary_csv = Path("data/kinu_29_light/4:12/kinu29_light_20g_flow_fit_psd_clog_impactrelief_wetbedchi_180s_summary.csv")
    if not summary_csv.exists():
        return

    params_fit, info = _load_measured_benchmark_state(flow_csv, summary_csv, refit=False, verbose=False)

    assert "4:12/kinu29_psd_bins.csv" in str(params_fit.psd_bins_csv_path)
    assert info["csv_path"].endswith("4:12/kinu29_light_20g_flow_profile.csv")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_measured_case_registry.py -v`
Expected: FAIL because benchmark loader still hardcodes `4:11` PSD path.

- [ ] **Step 3: Write minimal implementation**

```python
bins_csv = flow_path.with_name("kinu29_psd_bins.csv")
if not bins_csv.exists():
    raise FileNotFoundError(f"缺少 measured PSD bins CSV：{bins_csv}")
```

並在分析文件補上 `4:12` 為第二 measured case、`4:11` 仍為 baseline 的說明。

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_measured_case_registry.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pour_over/benchmark.py pour_over/analysis.py README.md
git commit -m "feat: support additional measured case-specific PSD loading"
```

### Task 4: 驗證與實驗紀錄

**Files:**
- Modify: `EXPERIMENT_LOG.md`

- [ ] **Step 1: Run targeted verification**

Run: `uv run pytest tests/test_measured_case_registry.py -v`
Expected: PASS

Run: `uv run python -m compileall pour_over`
Expected: compileall completes without syntax errors

- [ ] **Step 2: Run measured-case level checks**

Run: `uv run python - <<'PY'\nfrom pathlib import Path\nfrom pour_over.measured_io import load_flow_profile_csv\nfor case in ['4:11', '4:12']:\n    prof = load_flow_profile_csv(Path('data/kinu_29_light') / case / 'kinu29_light_20g_flow_profile.csv')\n    print(case, prof['t_s'][-1], prof['v_out_ml'][-1], prof['final_tds_pct'])\nPY`
Expected: `4:11` 與 `4:12` 都可成功載入；`4:12` 的 `final_tds_pct` 為 `None`

- [ ] **Step 3: Update experiment log**

```markdown
## 2026-04-12 17:19:00 +0800

- 改動：
  - 新增 `data/kinu_29_light/4:12` 的結構化 flow / thermal / PSD artifacts
  - 允許 measured flow profile 缺少 `final_tds_pct`
  - measured benchmark loader 改為優先讀取 case-local `kinu29_psd_bins.csv`
- 結果：
  - `4:12` 可作為第二 measured case 載入，不影響 `4:11` showcase baseline
- 判讀：
  - 新 case 僅進 validation 線，尚未升級為正式 benchmark
```

- [ ] **Step 4: Commit**

```bash
git add EXPERIMENT_LOG.md
git commit -m "docs: record kinu29 4-12 measured case onboarding"
```
