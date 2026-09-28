# Thermal-History Chain Audit Design

## Goal

針對 `kinu_28_light/4:20` 作為新驗證線，重畫目前 thermal-history 的物理邊界，修正 `core.py -> observation.py` 之間對 `T2` / `T1` 的語義錯位。

本設計的目標不是提高擬合分數，而是回答兩個物理問題：

1. `T2` 目前到底代表什麼物理量？
2. 現有 reduced-order thermal model 是否在必要處過度簡化？

## Scope

本次只處理 thermal-history。

納入：
- `pour_over/core.py` 內液相 / 粉體 / dripper 的熱狀態定義
- `pour_over/observation.py` 內 hold-up / server 的觀測層定義
- `fitting.py` 內 `T1` / `T2` 對照邏輯
- 以 `4:20` 為主、`4:12` 為回歸線的熱端驗證

不納入：
- `k_ext_coef`
- `max_EY`
- shell accessibility
- diffusion-path
- 任何只為 final TDS 擬合而增加的倍率參數

## Current Diagnosis

### What Is Wrong

目前 thermal chain 有三個物理問題：

1. `T2` 的模型定義錯位。
   現在 `fitting.py` 直接用 `sim["T_C"]` 對比量測 `T2`。
   但 `sim["T_C"]` 在 `core.py` 中是「液相 + 固相熱容耦合後的 lumped liquid node」，不是純出口液瞬時溫度。

2. 熱模型的空間解析度落後於濃度模型。
   濃度已採 axial layers，但溫度仍只有單一 `T`。
   這等於承認床內存在濃度歷史，卻否認床內存在熱歷史。

3. `observation.py` 只真正承接了 `T1` 的觀測語義，沒有承接 `T2`。
   目前 `T1` 經過 hold-up / server mixing，
   `T2` 卻直接取床內 bulk node，兩者不在同一條觀測鏈上。

### What Is Still Acceptable

以下簡化仍可接受：

- 單一 dripper thermal node
- 單一 server thermal node
- reduced-order hold-up volume

以下簡化已經過度：

- 用單一床內溫度 `T` 同時代表 bulk liquid 與 effluent temperature
- 用 `T1` 走 observation layer、`T2` 不走 observation layer

## Design Options

### Option A: Observation-Only Repair

做法：
- 保留 `core.py` 單一熱節點
- 重新定義 `T2`，使其來自 observation layer，而不是直接取 `sim["T_C"]`

優點：
- 風險最小
- 可以先消除明顯的語義錯位

缺點：
- 若床內 thermal stratification 才是主缺口，改善會有限

### Option B: Add Effluent Thermal State

做法：
- 保留床內 bulk thermal node `T_bulk`
- 新增最小必要的 effluent thermal state `T_effluent`
- `T2` 改由 `T_effluent` 或其 observation-layer 映射對應

優點：
- 以最小狀態數補上「床內 bulk 與即將流出液體不同溫」的物理事實
- 不必直接升級成 full axial thermal layers

缺點：
- 需要重新定義熱交換邊界與能量守恆接口

### Option C: Full Axial Thermal Layers

做法：
- 溫度跟濃度一樣做 axial layers

優點：
- 物理最一致

缺點：
- 目前過重
- 額外 state、可識別性與運算成本都會明顯上升

## Recommendation

採用 `Option B`，並以前置的 observation audit 作為第一步。

理由：
- `Option A` 太可能只修語義，不修主缺口
- `Option C` 在當前專案階段過重
- `Option B` 是最小但物理上可辯護的補強

## Proposed Thermal Boundary Redefinition

### State Model

現狀：
- `T`：床內 lumped liquid + coffee thermal inertia
- `T_dripper`
- `T_server`（在 observation layer）

目標：
- `T_bulk`：床內主液相與粉體耦合後的 bulk thermal state
- `T_effluent`：接近床底出口、將進入 cone outflow 的 effluent thermal state
- `T_dripper`
- `T_server`

### Physical Meaning

- `T_bulk`
  代表床內主體液相與粉體耦合後的平均熱狀態。
  這個 state 允許被咖啡固體熱容與 dripper exchange 主導。

- `T_effluent`
  代表真正對應 `T2` 感測位置的流出液熱狀態。
  它不應直接等同 `T_bulk`，而應反映：
  - 床底液體 residence history
  - 與較冷結構界面的局部熱交換
  - 與 bulk 的有限速率耦合

- `T_server`
  繼續代表下壺混合後 bulk temperature，對應 `T1`

## Formula-Level Rules

### Rule 1: No Direct `T_bulk -> T2`

禁止再直接把 `sim["T_C"]` 當 `T2`。

原因：
- `T_bulk` 是 storage state
- `T2` 是 outflow observation
- 兩者只有在「完全混合、零局部熱歷史」時才會相等
- 這在脈衝注水 V60 中不成立

### Rule 2: Effluent State Must Be Energetically Coupled

若新增 `T_effluent`，它必須是能量守恆 state，不可只是後處理平滑器。

允許：
- `bulk <-> effluent` 熱交換
- `effluent <-> dripper wall` 局部熱交換

不允許：
- 單純對 `T_bulk` 做經驗時間平滑後宣稱是新物理

### Rule 3: Observation Layer Must Stay Observation Layer

`observation.py` 只能處理：
- lag / hold-up
- server mixing
- ambient cooling of server

不應再承擔：
- 床內 thermal stratification
- 粉體與液體的主熱交換

這些應留在 `core.py`

## Validation Plan

### Primary Validation Line

主驗證線：`kinu_28_light/4:20`

原因：
- flow 已較穩定
- `T2` mismatch 明顯
- final TDS 亦保留，可檢查 thermal closure 是否誤傷 extraction history

### Regression Lines

- `kinu_29_light/4:12`
- `kinu_29_light/4:11`

原因：
- `4:12` 是現行正式 baseline
- `4:11` 是目前熱端最接近模型的案例，可當 sanity check

## Acceptance Criteria

### Must Hold

1. 不得惡化 flow fit 主線
   - `V_out RMSE` 不得明顯變差
   - `drain_time_error` 不得明顯變差

2. `T2` 的對比語義必須物理一致
   - `T2` 必須來自 effluent / outflow chain，而非 bulk storage state

3. 新 thermal closure 不得拿 extraction 參數吸熱誤差
   - 不改 `k_ext_coef`
   - 不改 `max_EY`
   - 不改 shell/path closure

### Desired Improvement

- `4:20` 的 `T2 RMSE` 顯著下降
- `T1 RMSE` 不惡化
- final TDS 若改善，只能視為次級結果，不作本輪主目標

## Implementation Phases

### Phase 1: Observation Audit Hardening

- 明確區分 `T_bulk`, `T_effluent`, `T_server`
- 修正 `fitting.py` 對 `T2` 的取值來源
- 不先引入新可調參數

### Phase 2: Minimal Effluent Thermal State

- 在 `core.py` 新增最小必要的 effluent thermal state
- 將 `T2` 綁到此 state 的觀測鏈
- 驗證能量守恆與回歸案例

### Phase 3: Re-evaluate Thermal vs Extraction Residual

- 若 `T2` 改善但 final TDS 仍低，再回頭檢查 extraction-history
- 若 `T2` 幾乎不動，才考慮更深的 thermal spatial closure

## Risks

- 若 `T2` 感測位置本身含顯著量測偏差，模型可能仍有下限
- 若真正主因是床內 thermal stratification 而非 effluent history，`Option B` 只會部分改善
- 若 observation 與 core 邊界劃錯，會造成熱量重複計算或遺漏

## Testing Strategy

- 單元測試：
  - `T2` 不再直接等於 `sim["T_C"]` 的語義測試
  - observation layer 的能量守恆測試

- 案例驗證：
  - `kinu_28_light/4:20`
  - `kinu_29_light/4:12`
  - `kinu_29_light/4:11`

- smoke check：
  - `uv run python -m compileall pour_over`

## Non-Goals

- 不在本輪處理 final TDS 缺口
- 不新增 purely empirical multiplier
- 不把 `T2` 問題回退成 server heat capacity 問題
