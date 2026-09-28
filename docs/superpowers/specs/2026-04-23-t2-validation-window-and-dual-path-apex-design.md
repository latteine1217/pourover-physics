# T2 Validation Window and Dual-Path Apex Design

## Goal

本設計只處理目前 thermal 問題中最小但最關鍵的兩件事：

1. `T2` 的主驗證窗應改為 `t >= 10 s`
2. `T2` 的物理解釋應從單一路徑 apex effluent，升級為最小雙路徑 apex thermal hypothesis

目標不是立刻改寫主熱方程，而是先把：
- 哪些資料可作主驗證
- 目前單一路徑模型到底缺了什麼物理

講清楚，避免後續又把感測器響應或局部接觸歷史誤塞進單一係數。

## Why This Spec Exists

最新三個 measured case 顯示：

- `4:20` 與 `4:12` 在 `10–15 s` 明顯偏熱
- `4:11` 在 `5 s` 明顯偏冷，但 `10 s` 後反而接近

這表示：

1. `0–10 s` 的 `T2` 很可能混入溫度計自身響應時間
2. 即使忽略 `0–10 s`，`10–20 s` 的 apex thermal history 仍不是單一路徑可解

因此，本輪必須先把驗證政策與物理假說分開：
- 先修 validation semantics
- 再決定要不要新增 apex local closure

## Scope

納入：
- `measured_io.py` / thermal CSV 的 `outflow_temp_use_for_fit` policy
- `fitting.py` 對 `T2` fit mask 的使用規則
- 以 `4:11` / `4:12` / `4:20` 為主的 early-time 誤差判讀
- apex `T2` 的最小雙路徑物理解釋

不納入：
- `T1` server model 重寫
- extraction / TDS closure
- 新的自由調參
- full axial thermal layers

## Current Diagnosis

### Observation Problem

使用者已明確指出：
- `T2` 測點在濾紙錐形頂點
- 溫度計升溫本身需要時間

因此 `t < 10 s` 的 `T2` 讀值不應直接當成 apex 液體真實瞬時溫度。

這代表：
- `t < 10 s` 的 `T2` 應為 diagnostic-only
- 不應納入主 fit / 主驗證 loss

### Physics Problem

即使忽略 `t < 10 s`，現有單一路徑 apex 模型仍無法同時解：

- `4:11` 的快速熱啟動
- `4:20` / `4:12` 的較慢升溫與後續接觸冷卻

目前 `core.py` 只允許一條：

- `T_bulk -> T_effluent -> T_dripper`

這條路徑不足以描述至少兩種不同的 apex 出流歷史。

## Proposed Policy Change

### Rule 1: T2 Main Validation Window Starts at 10 s

正式規則：

- `t < 10 s`：
  - `outflow_temp_use_for_fit = 0`
  - 僅保留為 diagnostic scatter
- `t >= 10 s`：
  - 保留為 `T2` 主驗證窗

理由：
- 這段資料混入探針熱慣性
- 不應用來反推 cone 內主熱方程

### Rule 2: Early T2 Remains Visible

雖然 `t < 10 s` 不進主 fit，
但不能刪掉，也不能在圖上隱藏。

原因：
- 它仍然提供 sensor / startup regime 的重要資訊
- 只是不能直接當成主熱模型的約束

## Dual-Path Apex Thermal Hypothesis

### Hypothesis

apex 的 `T2` 不是單一 effluent node，而是至少兩條路徑混合後的觀測：

1. `direct stream`
   - 較快到 apex
   - 接觸較少冷壁面
   - 升溫快
   - 較接近 `4:11`

2. `contact-cooled stream`
   - 在濾紙 apex / dripper tip 附近有較多停留與接觸
   - 升溫較慢
   - 之後仍帶有明顯接觸冷卻歷史
   - 較接近 `4:20` / `4:12`

### Why This Is Better Than One More Coefficient

若只加大或減小：
- `lambda_effluent_dripper`
- `effluent_holdup_scale`
- 任何單一時間常數

只能把所有 case 同方向推動。

但現在資料顯示不同 case 的 early-to-mid `T2` 誤差方向不同，
因此更合理的解釋是：

- 缺的是結構
- 不是缺一個更好的係數

## Minimal Next Implementation

若進入實作，最小方案應是：

### Phase A: Validation Policy Hardening

- 在 measured thermal pipeline 內，將 `t < 10 s` 的 `T2` 設為 held-out
- 補測試，鎖住這條規則
- 重算三案 `T2 RMSE`（限 `t >= 10 s`）

### Phase B: Dual-Path Apex Prototype

保留現有 `T_effluent` 作為：
- `contact-cooled stream`

新增一個最小 `T_stream` 或 `T_fast_apex` 作為：
- `direct stream`

觀測 `T2` 不直接等於其中任何一個，而是兩者加權。

### Constraint

本輪不允許：
- 新增 purely empirical loss-driven multiplier
- 直接把雙路徑權重做成自由擬合參數

優先使用現有物理量決定權重，例如：
- `gate_h`
- `Q_bed_transport`
- 必要時 `Q_pref / Q_bed`

## Acceptance Criteria

### Must Hold

1. `t < 10 s` 的 `T2` 不再進主驗證窗
2. `t >= 10 s` 的 `T2` 比較邏輯清楚且一致
3. 不修改 extraction 參數
4. 不拿 sensor lag 當作主熱方程錯誤

### Desired

1. 三個 case 的 `10 s` 後 `T2` 殘差型態更可解釋
2. `4:11` 與 `4:20` 不再被單一路徑 closure 強迫二選一

## Risks

- `10 s` 的切點仍是工程近似，不是嚴格感測器標定結果
- 若真實問題主要來自濾紙熱容而非雙路徑液流，雙路徑假說只會部分有效
- 若不先 harden validation window，就很容易把 sensor response 誤寫進主模型

## Non-Goals

- 本輪不追求更低整體 loss
- 本輪不處理 final TDS 缺口
- 本輪不重寫 server observation layer
