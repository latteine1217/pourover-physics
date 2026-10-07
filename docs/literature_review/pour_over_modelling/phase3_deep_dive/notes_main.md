### [@lee2026coffee] Coffee brewing trajectories from recipe-level records: a conservation-constrained framework for filter coffee

**Metadata**
- Authors: Hyun Seok Lee, Byoung-Yong Chang（Dept. Chemistry, Pukyong National University, Korea）
- Year: 2026（received 2026-06-12, accepted 2026-08-11, published 2026-08-15）| Venue: npj Science of Food（peer-reviewed, OA, CC BY 4.0）
- DOI: 10.1038/s41538-026-01074-1
- 讀的版本：Nature 提供的 unedited accepted manuscript PDF（35 頁）+ Supplementary Information DOCX
- Code/data: https://github.com/Byoung-Yong/FilterCoffee（Python；查詢時 1 star，最後 push 2026-06-04）；web app https://coffee.echemai.com

**Problem**
只有食譜等級資訊（粉量、水量、注水排程、研磨描述）時，能否用守恆約束的 reduced-order 模型
重建濾杯沖煮的水與溶質軌跡，並對未校準的研磨度預測終點。

**Key Contributions**
1. 錐形濾杯的 axisymmetric finite-volume 模型（24 軸層 × 6 徑向環，dt 0.05 s），水與溶質
   守恆殘差 1.96e-10 g / 1.55e-13 g。
2. 三個「有效量」（retained-water capacity `λ_ret`、effective hydraulic diameter `d_h`、
   effective release scale）在 coarse/medium/fine 各自擬合，再以 `q(D90) = a·D90^b` 冪律
   內插，預測 held-out 的 medium-coarse 與 medium-fine。
3. 套用到 53 筆公開食譜，只比對 finish time。
4. 有 identifiability 分析：Jacobian 有效秩 2；`d_h` 與 release scale 相關係數 −0.999。

**Methodology**
- 水：`W_in = W_pool + Σ W_j + Σ W_ret,j + W_bev`；pore capacity `ρ_w ε V_j`；retained water
  `W_ret,j = λ_ret · m_coffee,j`（單一係數，吸收毛細、膨潤、氣體、排水歷史）。
- 水力：Carman–Kozeny `K = d_h² ε³ / (α_K (1−ε)²)`，cell 間 Darcy
  `Q = K A ρ g /(μ L) · (S_j − S_res)^n`（形式上是 Corey 型）。`d_h` 是擬合的無因次比例，
  **不是由 PSD 計算**，而是吸收粒徑、填充、fines、濾紙阻力、bypass、channeling。
- 萃取：每個 PSD fraction（24 bins）一階釋放
  `dM_i/dt = −k_i f_wet f_sat f_u M_i`，`k_i = k_diff,ref (r_ref/r_i)² + k_surf,ref (r_ref/r_i)`，
  兩項比例固定，只擬一個 multiplier。三種釋放式以 AICc 選擇（19.06 vs 23.95 vs 36.56）。
- 無熱模型（未見溫度、黏度隨溫度變化的描述）。
- PSD：volume-density 分布（量測儀器在主文與 SI 中未見明確描述），視為 mass fraction；
  離散成 24 bins；用 D90 作為內插變數。
- 擬合：bounded nonlinear least squares（log 參數空間），每個校準條件 200 起點，共 600 次；
  χ² 以各條件各輸出的實驗 SD 標準化；1000 次 bootstrap 傳遞重複間變異。

**Experiments**
- 5 個研磨條件 × 3 重複 = 15 次沖煮；20 g 粉、300 g 水、同一錐形濾杯與濾紙。
- 注水：0–15 s 注 60 g、30–70 s 注 120 g、80–120 s 注 120 g。
- 量測：**只有終點**——drawdown time、beverage mass、TDS（VST refractometer）；EY 由前三者導出。
  **無時間解析出液曲線、無溫度量測。**
- D90：coarse 1814.6、medium-coarse 1683.3、medium 1010.1、medium-fine 743.5、fine 592.1 μm。
- Drawdown time（mean ± SD）：175.0 ± 6.0、181.7 ± 12.6、202.7 ± 26.7、233.7 ± 20.5、258.0 ± 29.5 s。
- Held-out（兩條件平均）：MAE drawdown 6.67 s、beverage mass 0.58 g、TDS 0.020 pp；6 個終點預測
  都在 1 SD 內。
- 公開食譜 53 筆：finish time MAE 42.15 s、RMSE 53.80 s、MAPE 22.66%、mean bias +33.40 s
  （42 筆模型偏長）。
- 擬合值（SI Table S3）：`d_h` 相對比例 coarse 0.469、medium 1.301、fine 2.971；
  `d_h(D90) = 0.975e5 · D90^−1.649`。

**Limitations**
- 作者承認：`d_h` 與 release scale 強烈補償（−0.999），終點資料只約束其組合；內部狀態（滯留水、
  溶質分配、時間軌跡）未經驗證；只在同一支豆、同一台磨豆機、同一濾杯與注水法內插；不能外推到
  其他系統；需要同步量測注水、濾杯總重、出液重、分段 TDS 才能檢驗軌跡。
- 讀者觀察：
  1. **`d_h` 隨研磨變細而變大**（0.47 → 2.97，冪律指數 −1.649）。Kozeny-Carman 中水力直徑應隨
     粒徑縮小而變小，擬合值方向相反；這代表 `d_h` 在補償 release scale 或其他未建模機制，而不是
     PSD→滲透率的物理關係。
  2. Held-out 是**內插**，且 medium-coarse 的 D90（1683）緊鄰 coarse（1815）；drawdown 的重複間
     SD 達 13–30 s，「在 1 SD 內」是寬鬆的門檻。
  3. 每個研磨度 3 個參數 × 3 個校準條件 = 9 個擬合量，對 27 個殘差；冪律再引入 6 個係數。PSD 對
     流動的影響完全靠擬合後內插，**不是由量測 PSD 經物理 closure 預測**。
  4. SI Table S3 中 medium 的 release scale 標為 0.00964，但其 bootstrap 區間是 8.0e-4–9.8e-4，
     疑似少一個 0（排版錯誤，未影響結論判讀）。
  5. 無熱模型；未用影片或秤取得時間序列。

**Relevance to the candidate claim**
- **部分重疊，且已發表**：「濾杯 reduced-order + measured PSD + held-out 研磨度預測 drawdown time」
  這個敘事，Lee & Chang 2026 已經做了。本專案若主張「首次以 PSD 預測跨研磨度的手沖流動」會被
  直接打回。
- **仍未被覆蓋的部分**：
  1. **時間解析的 V_out(t)**：他們只比對終點，明說需要同步量測才能驗證軌跡——這正是本專案的影片
     量測。
  2. **PSD 經物理 closure 進入水力**（d32 → Kozeny-Carman、fines → clogging、`r_pore` → 毛細
     滯留），而不是每個研磨度擬合有效直徑再冪律內插。若「單一 k₀ + 物理 PSD closure」能預測
     held-out 研磨度的整條曲線，比他們的 9 參數 + 冪律更強，也能回答他們 `d_h` 方向違反物理的問題。
  3. 熱模型與溫度量測。
  4. 外推（研磨度範圍外）而不只內插。
- 投稿時本文必須引用並正面比較；它也證明 npj Science of Food 接受這類題目。

**Code & Resources**
- Repository: https://github.com/Byoung-Yong/FilterCoffee（含沖煮量測、PSD、公開食譜資料、擬合結果）
- Web app: https://coffee.echemai.com
