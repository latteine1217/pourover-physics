# AGENTS.md

> 本體在 `AGENTS.md`；`CLAUDE.md` 與 `GEMINI.md` 只以 @ 匯入本檔，不要在那兩檔寫內容。

## 1. 專案目標

以物理學家與數值建模工程師的角色工作，維持一套可重現、可驗證、物理上可辯護的 reduced-order V60 simulator，而不是堆疊看似合理的 closure。本專案是 reduced-order porous-media、bin-resolved extraction、multi-node thermal model；不是 full CFD、full multiphase PDE solver，也不是只追求低 loss 的黑箱擬合器。

任何新增機制都必須先回答 `What:`（它代表什麼物理量）與 `Why:`（現有機制為何不足）。

## 2. 核心原則

1. 物理正確性優先於較低 loss；不得為了擬合數據而引入缺乏物理意義的調參或 closure。
2. measured data 優先於 proxy。
3. 可直接量測的量不得拿去吸收模型誤差。
4. 維持單一主模型：實驗性改動驗證失敗就還原，結論記入 `docs/experiment_log.md`，不以平行分支或開關保留舊版本。
5. `viz.py` 必須與主模型同步；`README.md` 在改動展示敘事或校準基準時同步。
6. 預設沖煮上限為 `180 s`，除非使用者另有要求。
7. 若新機制只是補償舊錯誤，應重寫 closure，不要再疊 multiplier。

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
- fast pool（破壁殼層，`δ_i = min(shell_thickness, R_i)`）與 slow pool（Crank 球形擴散首項）
  一階釋放，λ 公式見 `README.md`「Release laws」
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

- `rho_bulk_dry_g_ml`、`D10 / D50 / D90`、fines fraction、vessel / dripper equivalent heat capacity
- 量測預處理、影片量測、影片熱時序與觀測算子的常數與規則皆屬 Class B，清單見
  `docs/experiment_log.md` `[POLICY]`
- 停流液位算子常數 `STOP_TOL_ML` / `FINAL_WINDOW_S` / `STOP_SMOOTH_POINTS` **唯一來源在 `measured_io.py`**

### C. 允許少量標定的 closure 參數

- `k`、`h_cap`、必要時 `h_gas_0`
- `sat_rel_perm_exp`（Corey n，live）
- `k_beta`、`tau_lag`：已凍結為 Class B（`k_beta` = 該 case measured PSD clog index 算出值；`tau_lag` = `0.5 s`）
- 熱端：分享壺溫時序進 χ² 的影片 case，`U_liquid_dripper_W_m2K` live、`lambda_server_ambient`
  凍結 `3.7e-4 s⁻¹`；單點杯溫 case，`lambda_server_ambient` live、`U_liquid_dripper_W_m2K` 凍結 `194 W/(m²K)`
- 已被 identifiability 支持的少量附加 closure 參數

### D. 原則上不要先動的次級參數

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

## 5. PSD 規範

PSD 匯出來自使用者的 [coffeegrindsize](https://github.com/latteine1217/coffeegrindsize) fork，
欄位契約見 `README.md`「Particle-size distribution」；任一端改動欄位名稱或定義，必須同步
`pour_over/psd.py` 與 `tests/test_psd_invariants.py`。

若有 measured PSD：
- 必須優先使用 `psd_bins_csv_path`；不得再以 idealized fractal PSD 當主流程
- 絕對尺度由 raw CSV 的 `PIXEL_SCALE`（**px/mm**）決定；缺欄或非唯一一律 raise
- 模型尺度錨是 **Sauter `d32`**；`D10_measured_m` 是 resolution-bounded 的診斷量，
  **不得**用來縮放整條 PSD（研磨度縮放走顯式 `psd_diameter_scale`）

優先直接進主方程：`volume_fraction`、`num_fraction`、`surface_to_volume`（體積加權）、
`shell_accessibility`（縮放後解析重算，不讀舊欄）、`diameter_mid`、`aspect_ratio`、
`censored`（是否落在偵測下限附近）。只允許作 prior / regularization：histogram 摘要、aggregate span 指標。

堵塞至少拆為 `throat_clogging`（偏 number-based fines）與 `deposition_clogging`（偏 volume-based
fines），不得把所有堵塞效應重新塞回單一不可解釋的 `k_beta`。

## 6. 擬合規範

有影片版 profile（`*_flow_profile_video.csv`）時優先使用；紀錄表出液欄（`drained_volume_ml`）
有已知系統性偏差，不得優先進 χ²。無影片的 case 沿用紀錄表，並標 `drained_log_bias_suspected`。

主擬合目標：`V_out(t)`、interval mean `q_out`、`drain_time`、`cup temperature`。

禁止事項：
- 一次同時亂動水力、萃取、熱三套參數
- 用熱容吸收水力誤差
- 用萃取參數吸收 `V_out(t)` 誤差
- 不得以純粹降低 loss 為理由保留缺乏物理意義的擬合參數

**水力 stage（1/2/4）只最小化 `chi2_hydraulic`**（= volume + stop_time + `k_beta`
prior + Corey prior）；熱端（stage 5）與萃取（stage 7）以總 χ² 擬合。Why：水力 stage
時熱與萃取項反映的是尚未擬合的參數，最小化總 χ² 等於用水力吸收熱誤差。

**最終杯量**（TDS 分母、溶出質量項、stage 7 水力自洽 guard 的比較點）取完整 1 s
序列中**最後一個 `use_for_fit` 列**（`case["t_final_obs_s"]` / `v_out_final_obs_ml`），
不得取濾杯移開後的讀值。

每次 fitting 或重要改模後的必報清單見 `docs/experiment_log.md` `[POLICY]`「Fit 回報清單」。

CI 為 conditional slice（下界）。若某參數的 CI 兩端皆為 `None`，
代表在 ±2× 內不可辨識，應凍結它而不是繼續 fit。

**SOLVER preset：`rtol 1e-7`（`atol 1e-9`），任何 fit / identifiability 分析不得使用比這更鬆
的容差**（更鬆時 χ² 曲面的數值噪音會讓 optimizer 停進噪音凹陷，stage 判定與 identifiability
分級不可重現）。**ODE 必須在注水率斷點間分段積分**（`core._solve_piecewise`）。summary 寫出參數
必須 round-trip 精確（`repr(float(v))`），reload 與 fit 的 χ² 應逐位元相同。

**所有 fit / benchmark / identifiability 分析一律先經過 `_prepare_measured_case(preprocess=True)`**
（`pour_over/preprocess.py`，預設啟用）。raw CSV 為 Class A，不得改動；套用的修正必須寫入該 case
summary / benchmark CSV 的 `preprocess_corrections` 欄，供稽核。

若出現以下情況，先檢查模型，不要繼續調參：
- `k` 明顯偏離合理量級
- `k_beta` 偏離 PSD prior 超過約 0.6 dex（2σ）、需要極端 `tau_lag`（兩者現已凍結；要重新檢查時先確認是否該解凍）
- 需要不合理熱容
- `U_liquid_dripper` 逼近或超出 `[120, 550] W/(m²K)`（影片時序 case 的 fit bounds）
- `tau_tort` 被推到上界（這是刻意設計的失敗訊號）
- `reduced_chi2 ≫ 3` 且 `DW < 1.0`：殘差是結構誤差，缺的是機制不是參數

## 7. 視覺化與展示

### `viz.py`

- `plot_results()` 與 `plot_tds()` 必須能直接吃最新模型結果
- 所有 `compare_*` 以最新 calibrated baseline 為中心
- 不得繼續展示舊 baseline

### `README.md`

README 是給外部讀者的專案說明，主軸是「用了哪些物理機制去擬合實驗」：
- 現行主模型的物理機制與擬合方法、現行校準結果（引用最新 calibrated artifact 與圖檔）、
  已知限制；一律用現在式描述現況
- 不寫開發歷程：日期、F 代號、改動前後對照、被否定的機制、改名歷史都只寫在
  `docs/experiment_log.md`，README 只留一行指標
- 校準基準更新時，同步更新 README 的結果表與圖

## 8. 文件與輸出

語言、註解（What / Why）與輸出格式依全域 agent 協議。

### 實驗紀錄

執行了會產生新結論的實驗、掃描、fitting、benchmark 或 identifiability 分析，就必須同步更新
**`docs/experiment_log.md`**（本專案唯一的實驗紀錄；根目錄 `EXPERIMENT_LOG.md` 不得寫入）。
新 entry 一律插在 `[BASELINE]` 之後、既有 entry 之前，並同步更新 `[INDEX]` 表。

每筆至少包含：時間、改動內容、實驗結果、判讀或結論、artifact 路徑（若有）。時間應優先使用
artifact 檔案修改時間。若新實驗推翻舊結論，不得只改程式不改紀錄。

## 9. 工程規範

- 手動修改檔案時使用 patch；避免 ad-hoc 腳本整檔覆寫，除非必要

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
6. 若改動展示敘事或校準基準，需同步檢查 `README.md`
7. 若有新結論，更新 `docs/experiment_log.md`
8. 檢視該 case summary / benchmark CSV 的 `preprocess_corrections` 欄，
   確認預處理修正與預期一致（未預期的修正代表資料或程式有問題）

## 11. 目前默認展示基準

- 若無使用者另行指定，展示與比較基準以 `docs/experiment_log.md` `[BASELINE]` 為準。
- `kinu29 4:11`（紀錄表案例）不作展示基準。
- 頂層 legacy PSD 掃描不得作為展示基準。
