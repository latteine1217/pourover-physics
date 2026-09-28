# Low-Flow Apex Decoupling Design

## Goal

本設計只處理一個更小的 thermal-history 問題：

- 在 `10–20 s` 這段低流量 / 幾近停流的 apex phase，
  `T_effluent` 是否應該與 `T_bulk` 部分脫耦，而不是持續被 bulk 熱節點快速拉回。

本輪目標不是擴充成完整 dual-path apex model，
而是先驗證目前最小熱方程中的一個更基礎假說：

- `bulk <-> effluent` 熱耦合不應在所有流況下等強

## Why This Spec Exists

在已經排除：
- `T2 < 10 s` 的溫度計啟動期
- `T1` 的壺端感測器啟動期

之後，剩餘主缺口集中在：
- `4:20` / `4:12` 的 `10–20 s`

而這段時間的共同特徵是：
- `q_out` 已極小
- `T_effluent` 在模型內幾乎迅速貼回 `T_bulk`
- 量測 `T2` 卻仍明顯低於模型

這表示現有 `bulk_effluent_exchange` 很可能在低流量 regime 下過強。

## Scope

納入：
- `core.py` 中 `bulk_effluent_exchange`
- `core.py` 中 `advective_effluent_refresh`
- `4:11` / `4:12` / `4:20` 的 `10–20 s` apex 誤差判讀

不納入：
- `T1` server model
- full dual-path apex state
- extraction / TDS closure
- 新自由調參

## Current Diagnosis

目前 effluent 方程為：

```python
bulk_effluent_exchange = lambda_liquid_effluent * (T - T_effluent)
advective_effluent_refresh = (Q_bed_transport / V_effluent_T) * (T - T_effluent)
dT_effluent = advective_effluent_refresh + bulk_effluent_exchange - effluent_dripper_exchange
```

這裡有一個物理問題：

- `advective_effluent_refresh`
  會隨 `Q_bed_transport` 變小而自然減弱
- 但 `bulk_effluent_exchange`
  是常開的

因此當：
- 出流幾乎停止
- apex 主要剩下局部接觸液與滯留液

模型仍然持續用 bulk thermal node 直接加熱 `T_effluent`。

這會導致：
- `T_effluent` 在低流量 regime 太快貼回 `T_bulk`
- `4:20` / `4:12` 的 `15 s` 左右 `T2` 偏熱

## Physical Hypothesis

### Hypothesis

`bulk <-> effluent` 的熱耦合應取決於 hydraulic connection，
而不是永遠以固定強度存在。

也就是說：

- 高流量 / 連續液柱時：
  - bulk 與 apex effluent 熱耦合較強
- 低流量 / 近停流時：
  - apex 更像局部接觸滯留液
  - 應更受 dripper / filter contact 控制
  - 與 bulk 的直接熱交換應減弱

### Why This Is Better Than One More State First

若這個假說成立，
那麼目前的最小三節點：
- `T_bulk`
- `T_effluent`
- `T_dripper`

其實還有機會繼續使用，
只需要修正耦合條件，而不是立刻再新增一個 apex node。

只有當這個最小修正仍無法解釋 `10–20 s` 誤差時，
才值得進一步升級到 dual-path apex。

## Proposed Minimal Change

### Rule

將 `bulk_effluent_exchange` 改為：

- 受一個 `hydraulic_coupling_gate` 調節
- 當 `Q_bed_transport` / `liq_transport_gate` / `gate_h` 很小時，熱耦合同步減弱

概念上：

```python
bulk_effluent_exchange = gate_couple * lambda_liquid_effluent * (T - T_effluent)
```

其中 `gate_couple` 應優先由現有可解釋量決定，
不得先引入新的自由擬合參數。

### Candidate Gates

優先順序：

1. `liq_transport_gate`
   - 已經描述「可攜帶溶質 / 液相庫存」的活躍程度
   - 與 local liquid connectivity 最接近

2. `Q_bed_transport`
   - 直接對應 effluent refresh 的水力傳輸

3. `gate_h`
   - 可反映 head-driven hydraulic connection 是否仍存在

本輪應優先嘗試：
- 單一 gate
- 不疊 multiplier

## Acceptance Criteria

### Must Hold

1. 不新增自由擬合參數
2. 不修改 extraction 參數
3. `4:20` / `4:12` 在 `15 s` 左右的 `T2` 過熱應下降
4. `4:11` 不得被明顯打壞

### Desired

1. `T_effluent` 在 low-flow regime 不再快速貼回 `T_bulk`
2. `10–20 s` 的殘差型態更接近：
   - `4:20` / `4:12`：降低過熱
   - `4:11`：維持接近

## Risks

- 若真實問題來自 filter-paper thermal node 缺失，而不是耦合強度，這個修正只會部分有效
- 若 gate 選錯，可能把 `4:11` 的中段升溫過度壓低
- 若同時改 advective 與 exchange 項，會失去可判讀性；本輪應先只改一個主項

## Non-Goals

- 不在本輪做 dual-path apex state
- 不重寫 `T1` server observation
- 不追求整體 loss 最低
