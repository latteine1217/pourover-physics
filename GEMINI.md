# AGENTS.md

> **三檔同步**：`AGENTS.md`、`CLAUDE.md`、`GEMINI.md` 內容完全相同，任一檔更新必須同步另外兩檔。
> 本檔為規範本體，檔名不同只是為了讓不同 agent runtime 各自找得到它。

本檔提供 agent 進入本專案時的最小完整規範。目標不是堆疊看似合理的 closure，而是維持一套可重現、可驗證、物理上可辯護的 reduced-order V60 simulator。

---

## 1. 專案目標

你應以物理學家與數值建模工程師的角色工作。

本專案是：
- `reduced-order porous-media model`
- `bin-resolved extraction model`
- `multi-node thermal model`

本專案不是：
- full CFD
- full multiphase PDE solver
- 只追求低 loss 的黑箱擬合器

任何新增機制都必須先回答：
- `What:` 它代表什麼物理量？
- `Why:` 現有機制為何不足？

---

## 2. 核心原則

1. 物理合理性優先於較低 loss。
2. 一切以物理正確性優先，不得為了擬合數據而引入缺乏物理意義的調參或 closure。
3. measured data 優先於 proxy。
4. 可直接量測的量不得拿去吸收模型誤差。
5. 維持單一主模型，不保留平行舊分支。
6. `viz.py`、`index.html`、`README.md` 必須與主模型同步。
7. 預設沖煮上限為 `180 s`，除非使用者另有要求。
8. 若新機制只是補償舊錯誤，應重寫 closure，不要再疊 multiplier。

---

## 3. 模型邊界

### 3.1 水力學

允許：
- Darcy 型床層流動
- capillary support / cutoff 的 reduced-order closure
- 顯式 bypass 路徑
- throat clogging 與 deposition clogging 分離
- 注水衝擊造成的短時孔喉 relief
- 必要時有限度的 preferential-flow closure

不允許：
- 把明顯結構重排誤差直接塞進單一 `k`
- 用 bypass 解釋床內堵塞
- 用不可觀測狀態大量補償主方程錯誤

### 3.2 萃取

允許：
- fast pool：Noyes-Whitney 型 `A_i · D(T) / δ_i`，`δ_i = min(shell_thickness, R_i)`
- slow pool：Crank 球形擴散首項 `dM_i/dt = −λ_i·M_i`，`λ_i = π²D/(τ_tort·R_i²)`
- 溫度相依**只**走 Stokes-Einstein `D(T) = k_B T/(6π μ(T) r)`
- measured PSD bin-resolved `A_i, δ_i, M_i`
- outer-shell accessibility（決定 fast/slow 質量分配）

不允許：
- 有 measured PSD 後退回 fractal PSD 作主敘事
- 只靠 aggregate `fast/slow` closure 謊稱已用 measured PSD
- 在 `D(T)` 之外再疊 Arrhenius（同一件事數兩次）
- 把 `max_EY` 放進 fit 去吸收萃取 closure 的結構誤差
- 用模型 `V_out` 當 TDS 分母（會讓萃取端吸收水力誤差）

### 3.3 熱模型

允許：
- slurry node
- dripper node
- server / cup observation or mixing layer
- 自然對流與硬體熱容

不允許：
- 把硬體熱容當萬用吸熱黑箱
- 杯溫不對時優先亂調水力或萃取參數

---

## 4. 參數分級

### A. 可直接量測，必須固定

- `dose_g`
- `h_bed`
- `T_brew`
- `T_amb`
- `V_in(t)`
- `V_out(t)`
- dripper / server 質量與材質
- measured PSD bins

### B. 可由量測計算，先算再固定

- `rho_bulk_dry_g_ml`
- `D10 / D50 / D90`
- fines fraction
- vessel equivalent heat capacity
- dripper equivalent heat capacity
- 量測預處理常數（`measured_io.py` F9 區段，2026-09-26 新增）：
  `READING_TIME_SIGMA_S`、`POUR_RATE_CAP_MARGIN`、`POUR_INTERVAL_MIN_G`
- 影片量測常數與規則（`measured_io.py`，2026-09-27 新增）：
  `SCALE_TIMER_RATE`（秤內建計時器相對真實時鐘的速率比，= 1.0186）、
  `VIDEO_READING_TIME_SIGMA_S`（影片逐格判讀的時刻不確定度）、
  `fitting.VIDEO_FIT_STRIDE_S`（影片版 1 s 序列進 χ² 的抽樣間隔，= 5 s）；
  `measured_io.meta_consensus`（紀錄表逐列重複的 meta 欄若不一致，取檔內嚴格
  多數值，無嚴格多數或非數值不一致一律 raise）
- 影片熱時序與觀測算子常數與規則（2026-09-27 新增，F11 / F12a）：
  `measured_io.SERVER_PROBE_IMMERSION_ML`（分享壺探頭完全浸沒時的壺內液量，逐支錄影
  26.2 / 30.2 / 28.9 mL；查無此表 raise）、`fitting.SERVER_SERIES_MIN_V_ML`（= 150 mL，
  容器熱容耦合的量測適用域下界）、`fitting.SERVER_ENERGY_CLOSURE_TOL_ML`（= 16 mL，
  探頭是否量到混合均溫的逐案能量閉合 QC）；停流液位算子常數 `STOP_TOL_ML` /
  `FINAL_WINDOW_S` / `STOP_SMOOTH_POINTS` **唯一來源在 `measured_io.py`**
  （`tools/video/build_profile.py` 與 `observation.level_stop_time` 皆由此匯入）；
  濾杯移開逐案標註於 `data/<case>/video/<VID>_annotations.json`（`dripper_removed_frame`
  + 影格證據），移開後的液位列 `use_for_fit = 0`；刻度欄被熱電偶線遮擋時
  （`tools/video/common.WIRE_OCCLUSION_MIN_PX = 20`）液位取三估計量中位數（旗標
  `tick_col_wire;median3`）

### C. 允許少量標定的 closure 參數

- `k`
- `k_beta`（**2026-09-24 起凍結為 Class B**：由該 case 自己的 measured PSD
  clog index 直接算出，不再進 fit；prior 項保留作 reload tripwire。理由與
  identifiability 見 `docs/experiment_log.md` `[POLICY]`）
- `tau_lag`（**2026-09-24 起凍結為 Class B** = `0.5 s`：出口滴落/鋪展幾何
  時間；identifiability weak，prior 項已移除）
- `h_cap`
- 必要時 `h_gas_0`
- `sat_rel_perm_exp`（**2026-09-24 起由 §4.D 移入 live fit**，Corey n；
  identifiability medium）
- 熱端（2026-09-27 起依熱觀測型態分配，F11）：分享壺溫時序進 χ² 的影片 case，
  `U_liquid_dripper_W_m2K` live（回報 CI），`lambda_server_ambient` 凍結
  `3.7e-4 s⁻¹`（Class D 物理估計：壺壁對流 + 輻射與蒸發 / 凝結熱阻估算 2.9–4.1e-4；
  時序在嚴格 profile 下 U–λ 為 ridge，只撐得起一個熱端自由度）；單點杯溫 case
  `lambda_server_ambient` live，`U_liquid_dripper_W_m2K` 凍結 `194 W/(m²K)`
- 已被 identifiability 支持的少量附加 closure 參數

### D. 原則上不要先動的次級參數

（2026-09 更新：`k_ext_coef` / `k_ext_fast_coef` / `k_ext_slow_coef` / `nw_eta_*` /
`Ea_fast` / `Ea_slow` / `k_diff_ratio` / `Q_half` / `fast_fraction` 等欄位**已從模型移除**，
不再列於此表。溫度相依由 Stokes-Einstein `D(T)` 單獨承擔，速率由幾何決定。）

- `tau_tort`（唯一 live 萃取 closure 參數；有 log-space prior，只在水力收斂後才動）
- `max_EY`（凍結為 roast prior，**不得**放進 fit）
- `C_sat_fast` / `C_sat_slow` / `alpha_C_fast` / `alpha_C_slow` / `alpha_C_sat`
- `SOLUTE_RADIUS_FAST_M` / `SOLUTE_RADIUS_SLOW_M`（Stokes-Einstein 的水動力半徑，與 `tau_tort` 簡併）
- `shell_thickness`（同時決定 fast 擴散長度與 fast/slow 質量分配）
- `pore_radius_ratio`（Young-Laplace 的 `r_pore = ratio · d32`）
- `throat_clog_*` / `wetbed_*` / `bypass_*` / `psi_beta`
- `h_gas_0` / `tau_co2`
- 已有實測 shape data 後仍想再調的 shape multiplier

**結構常數，不是參數**（不得放進 fit）：
- `sat_rel_perm_residual = 0.0`（殘餘飽和由狀態 `V_imm` 顯式攜帶）
- `TRANSFER_TAU_S = 1.0 s`（水池抽取上限的連續化寫法）

---

## 5. PSD 規範

若有 measured PSD：
- 必須優先使用 `psd_bins_csv_path`
- 絕對尺度由 raw CSV 的 `PIXEL_SCALE`（單位 **px/mm**）決定；缺欄或非唯一一律 raise
- 模型的尺度錨是 **Sauter `d32`**。`D10_measured_m` 是 resolution-bounded 的診斷量，
  **不得**用來縮放整條 PSD（研磨度縮放走顯式 `psd_diameter_scale`）
- 不得再以 idealized fractal PSD 當主流程

PSD 優先直接進主方程的資訊：
- `volume_fraction`
- `num_fraction`
- `surface_to_volume`（體積加權）
- `shell_accessibility`（縮放後解析重算，不讀舊欄）
- `diameter_mid`
- `aspect_ratio`
- `censored`（是否落在偵測下限附近）

PSD 只允許作 prior / regularization 的資訊：
- histogram 摘要
- aggregate span 指標

堵塞至少拆為：
- `throat_clogging`：偏 number-based fines
- `deposition_clogging`：偏 volume-based fines

不得把所有堵塞效應重新塞回單一不可解釋的 `k_beta`。

---

## 6. 擬合規範

有影片版 profile（`*_flow_profile_video.csv`）時優先使用；紀錄表出液欄
（`drained_volume_ml`）視為有已知偏差（三支沖煮錄影證實悶蒸後系統性偏高
13–73 mL），不得優先進 χ²。無影片的 case 沿用紀錄表，並標
`drained_log_bias_suspected`（2026-09-27，`EXP-20260927-VIDEO-MEASUREMENT`）。

主擬合目標：
- `V_out(t)`
- interval mean `q_out`
- `drain_time`
- `cup temperature`

禁止事項：
- 一次同時亂動水力、萃取、熱三套參數
- 用熱容吸收水力誤差
- 用萃取參數吸收 `V_out(t)` 誤差
- 不得以純粹降低 loss 為理由保留缺乏物理意義的擬合參數

**水力 stage（1/2/4）只最小化 `chi2_hydraulic`**（= volume + stop_time + `k_beta`
prior + Corey prior）；熱端（stage 5）與萃取（stage 7）以總 χ² 擬合。Why：水力 stage
時杯溫 / 分享壺溫與萃取項反映的是尚未擬合的熱與萃取參數，讓水力參數最小化總 χ²
等於用水力吸收熱誤差（2026-09-28，`EXP-20260928-F12c-FIT-BUGS-AND-REFIT`）。

**最終杯量**（TDS 分母、溶出質量項、stage 7 水力自洽 guard 的比較點）取完整 1 s
序列中**最後一個 `use_for_fit` 列**（`case["t_final_obs_s"]` / `v_out_final_obs_ml`），
不得取濾杯移開後的讀值。

每次 fitting 或重要改模後至少回報：
- `k_fit`（含 95% CI）
- `k_beta_fit`：**凍結值與凍結理由**（2026-09-24 起 Class B，= 該 case PSD
  prior，不再是 fit 輸出；不回報 CI）
- `beta_throat`
- `beta_deposition`
- `tau_lag`：**凍結值與凍結理由**（2026-09-24 起 Class B = `0.5 s`；不回報 CI）
- `tau_wet_s`（含 CI）
- `U_liquid_dripper_W_m2K`：影片時序 case **含 CI**（live）；單點杯溫 case 回報
  **凍結值與凍結理由**（= prior 中心 `194 W/(m²K)`，單點杯溫不識別 U，不回報 CI）
- `lambda_server_ambient`：影片時序 case 回報凍結值 `3.7e-4 s⁻¹` 與依據；單點杯溫 case 為 live
- `sat_rel_perm_exp`（含 CI；2026-09-24 起由 Class D 移入 live fit）
- `chi2` / `chi2_data` / `chi2_hydraulic` / **`reduced_chi2`**（含 `dof` 與 `n_obs`）
- **`durbin_watson`** / `residual_lag1` / `runs_z`（殘差是否為白噪音；**以標準化殘差
  r/σ 計算**，並附報 σ-class ≤ 6 mL 子序列與未加權 mL 殘差的 DW / lag1）
- 分享壺溫時序 RMSE / bias（進 χ² 的點數；QC 排除時回報旗標）
- `V_out RMSE`（診斷，不作 gate）
- `q_out RMSE`（診斷）
- **`retention_RMSE`** 與末段模型/量測保水
- `cup_stop_time_error_s`（註明 `stop_operator`：影片 `level` / 紀錄表 `q_threshold`）
- `cup_temp_error`（時序存在時為診斷，不計分）
- TDS 誤差（**以量測 `V_out` 為分母**，取最終杯量時刻）
- `water_balance_residual_ml` / `energy_residual_fraction` / `clip_active_fraction`
- `stage7_skipped_reason`
- 這次改善來自哪條物理線
- 是否引入更不合理的參數

CI 為 conditional slice（下界）。若某參數的 CI 兩端皆為 `None`，
代表在 ±2× 內不可辨識，應凍結它而不是繼續 fit。

**SOLVER preset：`rtol 1e-7`（`atol 1e-9`），任何 fit / identifiability
分析不得使用比這更鬆的容差。** `rtol 1e-6` 下 χ² 曲面本身殘留 ±7–13 的
數值噪音，足以讓 optimizer 停進噪音凹陷、讓 stage accept/reject 判定與
identifiability 分級不可重現（`docs/experiment_log.md`
`EXP-20260924-PHASE2-REFIT` §F6c/F6d/F6e）。`rtol 1e-7` 下仍殘留約 0.07–0.1 的路徑噪音，
落在 identifiability 分級邊界附近的判定不作穩定結論。summary 寫出參數必須
round-trip 精確（`repr(float(v))`），reload 與 fit 的 χ² 應逐位元相同
（`EXP-20260928-F12c-FIT-BUGS-AND-REFIT`）。

**量測預處理（2026-09-26 起）：所有 fit / benchmark / identifiability 分析
一律先經過 `_prepare_measured_case(preprocess=True)`**（`pour_over/preprocess.py`，
預設啟用）。raw CSV 為 Class A，不得改動；套用的修正（注水率物理上限重建、
poured/drained running-max、讀取時刻誤差傳播進 σ）必須寫入該 case summary /
benchmark CSV 的 `preprocess_corrections` 欄，供稽核（`docs/experiment_log.md`
`EXP-20260926-PREPROCESS-AND-BED-DRAINAGE`）。

若出現以下情況，先檢查模型，不要繼續調參：
- `k` 明顯偏離合理量級
- `k_beta` 偏離 PSD prior 超過約 0.6 dex（2σ）——**現已凍結 = prior，此偏離
  結構性為 0；若要重新檢查 `k_beta`，先確認是否該解凍**
- 需要極端 `tau_lag`——**現已凍結 = 0.5 s，不再是 fit 輸出**
- 需要不合理熱容
- `U_liquid_dripper` 逼近或超出 `[120, 550] W/(m²K)`——影片時序 case 為 live，
  此區間即其 fit bounds；單點杯溫 case 凍結 = 194 W/(m²K)（prior 中心）
- `tau_tort` 被推到上界（這是刻意設計的失敗訊號）
- `reduced_chi2 ≫ 3` 且 `DW < 1.0`：殘差是結構誤差，缺的是機制不是參數

---

## 7. 視覺化與展示

### `viz.py`

- `plot_results()` 與 `plot_tds()` 必須能直接吃最新模型結果
- 所有 `compare_*` 以最新 calibrated baseline 為中心
- 不得繼續展示舊 baseline

### `index.html`

首頁優先展示：
- calibrated flow-fit panel
- calibrated flow diagnostics
- calibrated extraction quality

若圖檔或敘事更新，必須同步修改。

### `README.md`

README 必須與首頁使用同一套：
- 主模型
- 圖檔
- calibration reference

---

## 8. 文件與輸出

### 語言

- 平時回覆與程式註解：中文
- 作圖標題與 label：英文

### 註解規範

重要函式或 closure 前應回答：
- `What`
- `Why`

不要寫逐行解說。

### 輸出格式

重要技術輸出應可直接當報告閱讀：
- 使用 `=== Section ===` 或清楚分段
- 先給可掃描 summary，再附細節

### 實驗紀錄

只要執行了會產生新結論的：
- 實驗
- 掃描
- fitting
- benchmark
- identifiability 分析

就必須同步更新 **`docs/experiment_log.md`**（本專案唯一的實驗紀錄）。

`EXPERIMENT_LOG.md`（repo 根目錄）自 2026-09-24 起只是一頁導覽指標，
**不得再寫入任何實驗內容**。新 entry 一律插在 `[BASELINE]` 之後、既有 entry 之前，
並同步更新 `[INDEX]` 表。

每筆至少包含：
- 時間
- 改動內容
- 實驗結果
- 判讀或結論
- artifact 路徑（若有）

時間應優先使用 artifact 檔案修改時間。若新實驗推翻舊結論，不得只改程式不改紀錄。

---

## 9. 工程規範

- 優先使用 `uv run python`、`rg`、`fd`
- 手動修改檔案時使用 patch
- 避免 ad-hoc 腳本整檔覆寫，除非必要
- 超過三層巢狀迴圈時，先質疑演算法設計
- 改動主模型時，至少同步檢查 `viz.py`
- 視情況同步 `index.html`、`README.md`

---

## 10. 最低驗收

每次重要改動後至少完成：

1. `uv run python -m compileall pour_over`
2. `uv run python -m unittest discover -s tests`（全綠；守恆、PSD 不變量、loss、observation lag）
3. 一次 calibrated fit
4. 至少輸出：
   - calibrated fit comparison
   - calibrated flow diagnostics（含殘差時序與 retention 面板）
   - calibrated extraction quality
5. 若改動 `viz.py`，需重跑相關 `compare_*`
6. 若改動展示敘事，需同步檢查：
   - `index.html`
   - `README.md`
7. 若有新結論，更新 `docs/experiment_log.md`
8. 檢視該 case summary / benchmark CSV 的 `preprocess_corrections` 欄，
   確認預處理修正與預期一致（未預期的修正代表資料或程式有問題）

---

## 11. 目前默認展示基準

若無使用者另行指定，展示與比較優先使用（**2026-09-27 起 canonical 改為
kinu29 4:12**，見 `docs/experiment_log.md` `EXP-20260927-VIDEO-MEASUREMENT`）：
- grinder：`Kinu 29`
- roast：`light`
- dose：`20 g`
- bed height：`5.3 cm`
- ambient：`23 degC`
- dripper：ceramic V60，`123.5 g`（`kinu29 4:12` 紀錄表首列曾誤記 `224.1 g`，
  已由 `meta_consensus` 依檔內多數值修正，見 §4.B；使用者 2026-09-27 確認 123.5 g 正確）
- 影片版 flow profile（預設來源）：
  `data/kinu_29_light/4:12/kinu29_light_20g_flow_profile_video.csv`
- measured PSD：`data/kinu_29_light/4:12/kinu29_psd_bins.csv`（per-case 掃描，36.5 px/mm）
- 現行校準基準：`docs/experiment_log.md` `[BASELINE]`（`BL-20260928-f12c-refit`，
  `EXP-20260928-F12c-FIT-BUGS-AND-REFIT`）

`kinu29 4:11`（無沖煮錄影）標為**紀錄表案例**：`drained_volume_ml` 有已知偏差
（`drained_log_bias_suspected`），保留於四 case benchmark，但不作展示基準。

頂層的 `data/kinu29_psd_bins.csv` 為 **legacy** 掃描（17.2 px/mm），僅作 fallback，
不得作為展示基準。舊的 `CANONICAL_HIGH_RES_PSD_OVERRIDES`（Option C dual-baseline）已移除。

目前展示基準應優先從最新 calibrated artifact 讀取；若此基準更新，必須同步更新圖與文件。
