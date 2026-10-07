# Phase 3 — Deep Dive

Date: 2026-10-07 | 13 篇精讀。notes_main 由主 agent 撰寫；notes_A/B/C 由三個 subagent 撰寫，
主 agent 已回原文核對以下關鍵數字：Lee & Chang 全部數字（unedited manuscript + SI）、
Moroney 2019 的 d32 27.34/37.78 μm 與壓降 2.3/0.65 bar（PLOS 全文）、Wadsworth 2026 Table 1
與 α = 4.8080e3 m⁻¹（Strathprints PDF）、Corrochano thesis 的 KC 誤差 30%→520% 與 prefactor
189–1330（Birmingham eThesis 7176）。

**全文取得狀態**：Siregar 2026 與 Park 2025 只讀到摘要；Corrochano 2015 期刊版只讀到摘要，
數字取自其 EngD thesis；Cameron 2020 讀 accepted manuscript（圖與 SI 缺）；Lee 2023 讀 arXiv 版。

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

# Phase 3 deep dive — notes A

範圍：4 篇（Siregar 2026、Wadsworth et al. 2026、Park et al. 2025、Oec 2026）。
候選主張：「measured PSD + 單一 permeability closure，可在不重擬合的情況下跨研磨度預測 V_out(t) 與 drain time」。

全文取得狀態（2026-10-07）：

| key | 全文 | 來源 |
|---|---|---|
| wadsworth2026permeability | 全文 | Strathprints OA PDF（CC BY 4.0） |
| oec2026areapeak | 全文 | engrXiv PDF v1 |
| siregar2026teaching | **abstract-only** | IOPscience landing page；全文需訂閱，accepted-manuscript 連結被 bot CAPTCHA 擋下；arXiv 查無預印本 |
| park2025pourover | **abstract-only** | Semantic Scholar 摘要 + Penn Today / AIP 新聞稿；pubs.aip.org 有 bot 驗證，Unpaywall 判定 closed，arXiv 查無預印本 |

abstract-only 兩篇的 Methodology / Experiments 只寫摘要明載的內容，其餘標「未讀到」。

---

### [@wadsworth2026permeability] A model for the permeability of coffee pucks validated using X-ray computed micro-tomography

**Metadata**
- Authors：Fabian B. Wadsworth, Jérémie Vasseur, Jingwei Zhang, Katherine J. Dobson, Jonathan Gagné, Hannah M. Buckland, Jason P. Coumans, Michael J. Heap, Anna Theurel, Jackie E. Kendrick, Yan Lavallée, Christopher H. Hendon
- Year / venue：2026，*Royal Society Open Science* 13: 252031（received 2025-10-24，accepted 2026-01-30）
- DOI：10.1098/rsos.252031
- 全文來源：https://strathprints.strath.ac.uk/95930/1/Wadsworth-etal-RSOS-2026-A-model-for-the-permeability-of-coffee-pucks-validated.pdf（publisher version，CC BY 4.0）
- 同行審查：是（peer-reviewed journal article）

**Problem**
espresso 缺少一個能把研磨度、堆積程度與比表面積連到咖啡床 permeability 的通用 constitutive model。

**Key Contributions**
1. 用 percolation 型 permeability 律（Kozeny–Carman 的推廣），以「connected porosity ϕp」與「connected specific surface area s_p」為輸入，在無額外擬合下解釋 XCT + lattice-Boltzmann 得到的 k。
2. 提出比表面積 ansatz `s = 3(1−ϕ)/⟨R⟩ · exp(α⟨R⟩)`，用單一全域參數 α 吸收非球形 / 粗糙度隨粒徑增加的效應。
3. 給出 grind setting → ⟨R⟩ 的線性校準（同一台 Mahlkönig），組合成只需 `(G, ϕp)` 就能算 k 的封閉式（eq. 5.3）。
4. 彙整文獻上多種顆粒 / 燒結介質的資料，主張 percolation 模型在低孔隙率時優於 Kozeny–Carman。
5. 用 Forchheimer 方程與文獻的 k–k_I 關係估計 espresso 的 Forchheimer number，結論是 espresso 為層流但接近慣性區。

**Methodology**
- 主方程：Forchheimer `∇p = −(μ/k) q − (ρ/k_I) |q| q`（eq. 2.1），Darcy 為其非慣性特例。
- Kozeny–Carman：`k = ϕ³ / (W s²)`，W 常取 5（eq. 2.2）。
- Percolation：`k = [2(1 − (ϕ−ϕc)) / s²] (ϕ−ϕc)^b`（eq. 2.3），顆粒堆積的理論值 b = 4.4，文獻經驗範圍 4 ≤ b ≤ 4.4；本文對咖啡取 ϕc = 0、ϕ = ϕp，即 `k = 2(1−ϕ) ϕ^b / s²`（eq. 2.4）。
- 比表面積：球形 `s = 3(1−ϕ)/⟨R⟩`（eq. 2.5）；非球形 ansatz `s = 3(1−ϕ) exp(α⟨R⟩)/⟨R⟩`（eq. 2.6），α [L⁻¹] 為經驗參數。作者明確寫出可用 `⟨R³⟩/⟨R²⟩`（即 Sauter 型尺度）取代 ⟨R⟩，並定義 polydispersivity `S = ⟨R⟩⟨R²⟩/⟨R³⟩`；但後續分析一律用 ⟨R⟩（area-equivalent radius 的平均）。
- 無因次化：`k̃ = k/k_s`，`k_s = 2(1−ϕp)/s_p²`；`s̃_p = s_p⟨R⟩`。
- 研磨度校準：`⟨R⟩ = βG + R0`，β = (4.3505 ± 0.0768) × 10⁻⁵，R0 = (1.0160 ± 0.0532) × 10⁻⁴ m。
- PSD 進入方式：Camsizer X2（Microtrac MRB，dynamic image analysis，dry dispersion，可量 8×10⁻⁷ ≤ R ≤ 8×10⁻³ m），取 area-equivalent radius R、R_min、R_max；三者分佈相近，故只用 R。PSD 只以 ⟨R⟩（以及 S）進入模型，**不是 bin-resolved**。
- Permeability「量測」：未壓實的粉放入 5 mm 吸管，Nikon XTH 180 XCT（55 kV、187 µA、3142 projections、voxel 2.99 µm / 2.69 µm），二值化後以 LBflow（D3Q15）在三個主軸方向做 lattice-Boltzmann，取平均 k 與標準差；流體性質用空氣（作者論證 k 與流體無關），1.36×10⁻⁷ ≤ Re ≤ 2.51×10⁻⁶。ϕp 與 s_p（marching cubes）都從 XCT 直接量。
- 擬合 vs 量測：ϕp、s_p、k 皆為 XCT 量測；β、R0 由 PSD 對 G 擬合；α 為對 s̃_p 資料的單一全域擬合；b 固定 4.4，ϕc 固定 0。

**Experiments**
- 樣本：2 種咖啡（Tumba / Rwanda、Guayacán / Colombia，Square Mile Coffee Roasters）× Mahlkönig grind setting 1–11 = 22 個樣本；Guayacán G=2 在 Table 1 中 XCT 欄位為 "no data"，故 permeability 有 21 筆。
- 幾何：不是濾杯，是 5 mm 吸管中未壓實的乾粉堆。沒有任何實際注水 / 出液量測（作者說明桌上型氣體 permeameter 因 screen 問題不可行）。
- 驗證型態：Fig. 5 用量測 s_p 把 k 無因次化後，KC 與 percolation 都「無需擬合」吻合；Fig. 6b 改用模型 s_p 與模型 ⟨R⟩ 仍「合理描述」k。α 是在同一批資料上擬合 → **in-sample calibration，沒有 held-out grind setting 或 held-out coffee**。
- 數值結果（Table 1 / 正文）：
  - ⟨R⟩：Guayacán 2.11×10⁻⁴（G1）到 8.18×10⁻⁴ m（G11）；Tumba 1.92×10⁻⁴ 到 7.65×10⁻⁴ m。
  - ϕp 範圍約 0.3707–0.6733；s_p 17,105–46,688 m⁻¹。
  - k（LB）範圍 1.58×10⁻¹¹（Guayacán G11）到 1.91×10⁻¹⁰ m²（Tumba G6）。
  - α = (4.8080 ± 0.0379) × 10³ m⁻¹（單一全域擬合）。
  - G 1–3 呈雙峰 PSD（主峰 10⁻⁴–10⁻³ m、fines 峰 10⁻⁶–10⁻⁵ m），G 4–11 為單峰；PSD、⟨R⟩、S 與咖啡品種無關。
  - espresso 估算：1 ≤ G ≤ 4 → 145.11 ≤ ⟨R⟩ ≤ 275.62 µm；q = 5.36–5.74×10⁻⁴ m/s；μ = 3×10⁻⁴ Pa·s；假設 0.3 ≤ ϕp ≤ 0.5 → 0.0161 ≤ Fo ≤ 0.0639。
  - 慣性 permeability 採 `k_I = exp(γ2 k^τ)`，γ2 = −1.71588、τ = −0.08093（陶瓷資料，非咖啡）。

**Limitations**
- 作者承認：porosity 沒有控制（未壓實，ϕp 不隨 G 系統變化）；LB 只在 creeping flow，不能直接給 k_I；k–k_I 關係來自非咖啡介質；fines migration 會造成下游細粉層，建議以層狀 harmonic mean `k_puck = Σw_i / Σ(w_i/k_i)` 處理但未實作；吸水膨脹（引文稱最多 30% 體積）可能大幅改變 k，需另行研究；⟨R⟩–G 關係依 grinder / burr / 校準而異。
- 讀者觀察：
  - 「驗證」是 XCT 影像上的數值模擬 k，不是實際水流；乾、未潤濕、未壓實、無 CO₂、無 swelling、無 fines 遷移，與 V60 床（飽和、重力驅動、會壓密與堵塞）差距大。
  - α 與驗證資料同源，屬 calibration；exp(α⟨R⟩) 在粗研磨的放大倍率很大。以 Table 1 Guayacán G11 為例，球形公式 3(1−ϕp)/⟨R⟩ ≈ 1.8×10³ m⁻¹，量測 s_p = 46,688 m⁻¹，差約 26 倍。這已超出單純「顆粒稜角」能解釋的量級，可能混入影像解析度或表面粗糙度的效應；作者沒有討論此量級。
  - 由於 s_p 隨粗研磨上升，Table 1 中 k 對 G **非單調**（例：Guayacán G4 k = 1.55×10⁻¹⁰，G11 k = 1.58×10⁻¹¹ m²）。若這是真實物理而非 XCT 解析度假象，則「d32 越大 → k 越大」的 Kozeny–Carman 直覺在粗端不成立。
  - 第 6 節的膨脹範例寫「k 從 3.9×10⁻¹⁶ m² 變為 8.1×10¹⁷ m²」（PDF 原文如此，後者指數顯然排版錯誤），且 3.9×10⁻¹⁶ 與 Table 1 的 LB 量級（10⁻¹¹–10⁻¹⁰）差五個數量級，作者未說明；此數字不宜引用。
  - 只用 ⟨R⟩，fines 只透過 S 間接出現；沒有 throat clogging 或 deposition 的概念。

**Relevance to the candidate claim**
- 重疊：這是目前最接近「PSD → permeability、跨 11 個研磨度、單一 closure」的工作：一條 percolation 律（b 固定）加上一個全域 α，就從 (⟨R⟩, ϕp) 得到 k；跨兩種咖啡沒有逐 case 重擬合。
- 不重疊：(1) 沒有任何 V_out(t)、drain time 或實際沖煮；(2) 不是重力驅動、不是 V60 錐形、不是飽和 / 非飽和床；(3) ϕp 由 XCT 量測，候選主張的 ϕ 需另外得到（量測 h_bed 與 bulk density）；(4) PSD 只以平均半徑進入，不是 bin-resolved，也沒有 fines 堵塞；(5) 驗證是 in-sample（α 與資料同源），不是 held-out prediction。
- 對候選主張的意義：它**沒有**完成 PSD→flow 的沖煮預測，所以候選主張的「跨研磨度預測 V_out(t)」仍是空位；但必須引用它作為 permeability closure 的直接前例，並回應兩點。第一，作者明確把 ⟨R³⟩/⟨R²⟩（d32 型）列為可選尺度但未採用，我們用 d32 錨點需要說明理由。第二，他們發現只靠球形比表面積的 KC 在粗研磨失效，必須加入隨粒徑增長的 s 修正；若我們的單一 k closure 只用 d32²，粗端可能出現系統性偏差。
- 可借用：percolation 型 `k ∝ (1−ϕ)ϕ^b / s²`（b = 4.4）可作為 Kozeny–Carman 的替代；層狀 harmonic mean 與我們的 fines 堵塞 / deposition 概念相容。

**Code & Resources**
- Data accessibility：所有 permeability、pore-network 與 PSD 資料以 .zip 附在期刊頁面（"provided as a .zip file uploaded here"）。
- 軟體：LBflow（lattice-Boltzmann）；marching cubes 用 Vasseur & Wadsworth 的 Python 實作（文中引用 [20]）。未列出公開 code repo。

---

### [@oec2026areapeak] An area-weighted particle-size peak from image analysis predicts total dissolved solids across grinder types

**Metadata**
- Author：Naoya Oec（Dogrun Inc., Shizuoka, Japan；ORCID 0000-0002-7491-4994）
- Year / venue：2026，engrXiv preprint v1（PDF 列印日期 2026-07-05）
- DOI：10.31224/7507
- 全文來源：https://engrxiv.org/preprint/download/7507/12236/10555（PDF，以 pdftotext 抽出全文閱讀）
- 同行審查：否（preprint）
- Competing interest：作者是 GrindGuide（影像式粒徑量測服務）的開發者，本文特徵預計導入該服務。

**Problem**
從影像分析得到完整 PSD 後，哪一個 PSD 特徵最能預測 TDS，且不受 grinder 種類影響。

**Key Contributions**
1. 用同一條影像 pipeline 系統比較 11 種 PSD 特徵與 TDS 的 Spearman 相關。
2. 提出 area_weighted_peak（以每顆粒實測投影面積加權的 KDE mode），pooled ρ = −0.949，兩台 grinder 皆 |ρ| > 0.94。
3. 顯示 D32 與 Da50（同一面積加權分佈的 mean 與 median）幾乎同樣好且跨 grinder 一致；count-weighted（kde_peak、Dn50）與 volume-weighted（Dv50、D43）則依 grinder 而變。作者據此主張「面積加權」本身才是關鍵，而不是挑哪一個位置統計量。

**Methodology**
- 無物理模型，純相關分析（scipy.stats.spearmanr）。
- 影像：iPhone 14 Pro + 10× 光學變焦鏡頭（等效焦距 75 mm），環形 LED 正上方照明；粉撒在畫有 50 mm 圓的紙台上，以圓直徑做每張的 px→mm 自校準。
- 分割：headless Fiji，8-bit、ImageJ Default/IsoData 自動閾值、Clear Outside；Python 過濾 0.1 mm ≤ Feret ≤ 3.0 mm 且投影面積 ≥ 0.01 mm²。
- 粒徑：Feret diameter（最大卡徑）；D32 / D43 / Dv50 / Da50 / Dn50 另以 ECD = 2√(Area/π) 計算（D32 = Σd³/Σd²）。每樣本撒三次、照三張、顆粒合併（replicate_combined）；過濾後每樣本 138–662 顆。
- KDE：Gaussian kernel，Scott's rule 帶寬，1024 點網格取 argmax；三種權重：無權重、√Area、Area。
- PSD 如何進入：只作為單一標量特徵與 TDS 做秩相關，不進任何萃取或流動方程。

**Experiments**
- 咖啡：單一產地（Nicaragua Buenos Aires Farm，fully washed，medium roast）。
- 沖煮：**cupping 式浸泡**，非 pour-over：8 g 粉 + 150 g 96 °C 水（1:18.75），4 min 攪拌 4 次撇渣，5 min 用針筒取約 2 mL，經 0.45 µm 濾膜，冷卻到 25.2–25.4 °C，以 DiFluid R2 Extract 量三次取中位數。
- Grinder：LAGOM Casa（65 mm conical）設定 8, 13, 15, 17, 19, 21；Timemore Sculptor 078（SSP flat）設定 2, 4, 7, 11, 14, 17。每設定一次研磨一次沖煮，共 12 樣本。
- 驗證型態：相關分析（描述性），沒有 held-out 預測，也沒有迴歸模型的外推測試；per-grinder n = 6，作者說明 p 值僅供參考。
- 結果（Table 1，pooled / Casa / Sculptor 的 ρ）：
  - area_weighted_peak：−0.949 / −0.986 / −0.943
  - D32：−0.893 / −0.899 / −0.943
  - Da50：−0.890 / −0.899 / −0.943
  - std：−0.855 / −0.899 / −0.886
  - mean：−0.802 / −0.986 / −0.886
  - sqrt_area_weighted_peak：−0.473 / −0.609 / −0.943
  - Dv50：−0.448 / −0.754 / −0.314
  - D43：−0.434 / −0.841 / −0.314
  - kde_peak：−0.112 / −0.812 / +0.143（符號反轉）
  - Dn50：−0.060 / −0.382 / +0.314
  - median：−0.021 / −0.232 / −0.771
- 沒有量測流量、drain time 或出液。

**Limitations**
- 作者承認：N = 12、只有兩台 grinder（四台以上的驗證進行中）；未與 laser diffraction 等外部方法比對粒徑；只用浸泡式 cupping，其他沖法未測；單一產地與烘焙度；光照與撒粉方式的穩健性仍在研究。
- 讀者觀察：
  - Feret ≥ 0.1 mm 的過濾把 < 100 µm 的 fines 全部排除，因此「count-weighted 特徵失效」部分可能是解析度下限造成，而非物理。
  - 每樣本 138–662 顆，對 KDE mode 與高階矩（D43、Dv50）的統計穩定性偏低；粗端少數大顆粒會主導 d³、d⁴ 權重，這可能正是 Dv50 / D43 不穩的原因。
  - Spearman 只檢驗單調性；12 點中研磨度本身就與 TDS 單調相關，任何隨研磨度單調變化的特徵都會得到高 |ρ|。因此 pooled ρ 主要反映「跨 grinder 是否落在同一條單調曲線上」，這比單一 grinder 內的 ρ 更有資訊量。
  - 單次沖煮、無重複，TDS 的沖煮間變異沒有量化。
  - 存在利益衝突（GrindGuide）。

**Relevance to the candidate claim**
- 重疊：同樣以低成本影像 PSD 為輸入，並獨立支持「面積加權尺度（D32 / Da50）是跨 grinder 穩定描述子」。這與本專案以 Sauter d32 為尺度錨的選擇一致，可作為 d32 錨點的旁證。
- 不重疊：目標量是 TDS（萃取），不是流動；浸泡式，沒有 V_out(t) 或 drain time；沒有物理模型；屬相關性，不是預測。
- 對候選主張的意義：它**沒有**做 PSD → flow；但 Sauter d32 跨 grinder 有效的結論只在萃取端成立，對 permeability 端沒有直接證據（permeability 對 fines 與 throat 的敏感度和萃取不同）。引用時應限定在萃取端。

**Code & Resources**
- Data：figshare https://doi.org/10.6084/m9.figshare.32897561（particle-level CSV、tds_log.jsonl、particle_size_stats.csv、feature_table_for_publication.csv）
- Code：https://github.com/dogrun-inc/coffee-tds-particle-features

---

### [@siregar2026teaching] Coffee brewing as a context for teaching porous media flow and mass transfer principles

**Metadata**
- Author：Syahril Siregar（Universitas Indonesia，依 WebFetch 摘要頁）
- Year / venue：2026，*European Journal of Physics* 47(3) 035101，published 2026-05-04
- DOI：10.1088/1361-6404/ae614b
- 全文來源：**abstract-only**。IOPscience landing page 顯示需訂閱（"not registered by an institution with a subscription"）；Unpaywall / Semantic Scholar 標為 HYBRID（CC BY-NC-ND），但實際連結仍是 landing page；accepted-manuscript（/ampdf）被 bot CAPTCHA 擋下；arXiv API 以作者與關鍵字查無此文預印本。同作者另有 arXiv:2601.03663（"A Minimal Thermo-Fluid Model for Pressure-Driven Extraction in a Moka Pot"），本筆記未讀。
- 同行審查：是（期刊；教學類論文）

**Problem**
為大學物理 / 傳輸現象課程提供一個以重力驅動 pour-over 為情境的簡化 porous-media 流動與萃取模型。

**Key Contributions**（依摘要）
1. 把 pour-over 當作錐形幾何中的非穩態多孔介質流。
2. 耦合 Darcy's law、質量守恆與一條 phenomenological extraction equation，描述水位、流量與溶質濃度的共同演化。
3. 指出錐形幾何使儲水體積對水位呈非線性關係，導致出液流量呈「characteristic cubic scaling」（相對於等截面模型）。
4. 以數值模擬展示 bed permeability 的改變如何影響 brew time 與 extraction efficiency。

**Methodology**
- 依摘要：Darcy + mass conservation + 錐形儲水幾何 + phenomenological extraction。具體方程、cubic scaling 的推導對象（對水位 h？）、extraction 方程形式、參數值：**未讀到**。
- 擬合 vs 量測：摘要明言模型「requires no new experimental input beyond literature values for physical properties」，即不擬合任何實驗。
- PSD：摘要未提及 PSD；permeability 似為參數掃描變數（未讀到確認）。

**Experiments**
- 摘要未提及任何實驗或資料比對；只有數值模擬。研磨度設定、樣本數、儀器：無 / 未讀到。
- 驗證型態：無（教學示範）。

**Limitations**
- 作者在摘要自稱 "simplified physical model"；其他作者承認的限制：未讀到。
- 讀者觀察（僅依摘要）：無實驗驗證；permeability 是輸入參數而非由 PSD 推得；沒有 capillary retention、bypass、clogging 或熱模型的跡象（未讀全文，不能確認）。

**Relevance to the candidate claim**
- 重疊：同樣是重力驅動、錐形 V60 型幾何、Darcy + 質量守恆的 reduced-order 沖煮模型，並討論 permeability 對 brew time 的影響。這是在「V60 錐形幾何 + Darcy 排水」層級最直接的同類前例（且已刊於期刊），必須引用，且我們的錐形儲水 / 排水推導需與其 cubic scaling 對照。
- 不重疊（依摘要）：沒有 measured PSD、沒有 PSD→k closure、沒有實驗 V_out(t)、沒有跨研磨度預測。候選主張的核心（PSD 驅動、對實測 V_out(t) 的跨研磨度預測）不被此文覆蓋。
- 待補：取得全文後確認 (a) cubic scaling 的確切形式；(b) 是否有任何與實測資料的比較；(c) permeability 是否與粒徑連結（如 Kozeny–Carman）。

**Code & Resources**
- 未讀到（摘要未提）。

---

### [@park2025pourover] Pour-over coffee: Mixing by a water jet impinging on a granular bed with avalanche dynamics

**Metadata**
- Authors：Ernest Park, Margot Young, Arnold J. T. M. Mathijssen（Department of Physics and Astronomy, University of Pennsylvania）
- Year / venue：2025，*Physics of Fluids* 37(4)；Penn Today 新聞稿標文章號 043332（未在出版社頁面核對）
- DOI：10.1063/5.0257924
- 全文來源：**abstract-only**。Semantic Scholar 摘要；Unpaywall 判定 `is_oa: false`、無 repository copy；pubs.aip.org 回 403 / bot 驗證頁；arXiv API 以 Mathijssen + coffee 查無預印本。另讀了 Penn Today 與 AIP Publishing 新聞稿，兩者都沒有給出數值。
- 同行審查：是（期刊）

**Problem**
pour-over 中，注水 jet 衝擊床面上方水層與顆粒床時，內部如何混合？能否透過調整注水方式提高萃取效率以減少用豆量？

**Key Contributions**（依摘要）
1. 用透明 silica gel 顆粒取代咖啡粉，置於玻璃錐中，以 laser sheet + 高速攝影觀察 jet 下方的顆粒運動。
2. 發現 avalanche effect：即使是溫和的 pour-over jet，在不同注水高度下都會造成強烈混合。
3. 漂浮顆粒層對此混合沒有顯著影響。
4. 以真實咖啡粉量測 TDS / extraction yield，結論是用較慢但較有效的注水延長混合時間，可以調整萃取；可用 flow rate 與 pour height 調整濃度，而不必增加豆量。

**Methodology**
- 依摘要與新聞稿：silica gel 顆粒 + 玻璃錐 + laser sheet + 高速攝影；gooseneck kettle；變因為注水高度與流量。
- 新聞稿轉述作者建議：在保持 laminar（jet 撞到粉床時不破碎）的前提下盡量提高注水高度；太高時 jet 破碎成液滴並夾帶空氣，反而降低萃取效率。
- 方程、無因次參數、PSD 使用、哪些量被擬合：**未讀到**。

**Experiments**
- 依摘要：(1) silica gel 模型實驗（不同注水高度）；(2) 真實咖啡粉的 extraction yield / TDS 量測。
- 樣本數、研磨度、粒徑、注水高度與流量數值、TDS 數值：**未讀到**（新聞稿也未給）。
- 驗證型態：實驗觀察 + 萃取量測；摘要未顯示有預測模型或 held-out 驗證。

**Limitations**
- 作者承認：未讀到。
- 讀者觀察（僅依摘要）：silica gel 的密度、潤濕性、粒徑分佈與咖啡粉不同（無 CO₂、不膨脹、無溶出）；焦點是注水區的混合，不是床的出液水力；摘要沒有出液流量或 drain time。

**Relevance to the candidate claim**
- 重疊：同樣是 pour-over 錐形濾杯；說明注水 jet 會造成床面顆粒 avalanche 與再懸浮。這與本專案「注水衝擊造成的短時孔喉 relief」以及 fines 再分佈的假設有關，可作為該 closure 的定性物理依據。
- 不重疊：沒有 PSD→permeability、沒有 V_out(t) 或 drain time 預測、沒有跨研磨度的流動比較（依摘要）。
- 對候選主張的意義：未佔據候選主張。它反而提示一個威脅：若注水方式（高度 / 流量）會改變床的混合與顆粒重排，則「單一 permeability closure 不重擬合」在注水手法不同的沖煮間可能失效。驗證設計應固定注水高度與流量，或在討論中列為限制。

**Code & Resources**
- 未讀到。

---

## 對候選主張的綜合判讀

1. 四篇都**沒有**做「measured PSD → 單一 permeability closure → 跨研磨度預測重力驅動沖煮的 V_out(t) / drain time」。在這四篇範圍內，候選主張的核心仍未被佔據。
2. 最接近的是 Wadsworth et al. 2026：跨 11 個研磨度、單一 percolation closure + 單一 α，從 PSD 平均半徑與 ϕp 得到 k。但它是 XCT 上的 LB 模擬、乾燥未壓實的粉堆、in-sample 校準，沒有實際流動。它也顯示球形比表面積在粗研磨會低估約一個數量級，對「只用 d32 的 KC closure」是直接的風險訊號。
3. Siregar 2026（abstract-only）是錐形 V60 + Darcy 排水的同類期刊前例，但沒有 PSD 也沒有實驗；論文中需對照其 cubic scaling。
4. Oec 2026 支持 d32 / 面積加權尺度跨 grinder 有效，但只在萃取（TDS）端；Park et al. 2025 提醒注水動力學會改變床況。

# Phase 3 Deep Dive — Notes B（Moroney 2019 / Cameron 2020 / Foster 2025 / Lee 2023）

> 待檢驗 claim：「measured PSD + 單一 permeability closure，可在不重擬合的前提下，跨研磨度預測 V_out(t) 與 drain time」。
> 本檔所有數字皆取自實際讀到的全文；未讀到者明確標示。

---

### [@moroney2019] Analysing extraction uniformity from porous coffee beds using mathematical modelling and computational fluid dynamics approaches

**Metadata**
- Authors：Kevin M. Moroney, Ken O'Connell, Paul Meikle-Janney, Stephen B. G. O'Brien, Gavin M. Walker, William T. Lee
- Year / Venue：2019，PLOS ONE 14(7): e0219906（epub 2019-07-31）
- DOI：10.1371/journal.pone.0219906
- 實際讀到的全文來源：PLOS 官方 JATS XML 全文（journals.plos.org manuscript file），含正文、Table 1–2、圖說；方程式本體為 MathML，轉文字時遺失符號細節，僅由敘述得知各式含義。S1/S2 Appendix 與影片未讀。
- 狀態：peer-reviewed

**Problem**
在 packed coffee bed 中，flow 不均勻（由幾何與注水方式造成）會使床內局部 extraction yield 產生多大的空間變異，以及如何以 CFD 量化這個變異。

**Key Contributions**
1. 以 ANSYS Fluent Euler-Euler 多相框架（固相靜止）+ Gidaspow drag（其 Darcy 項即 Kozeny-Carman）建立 2-D axisymmetric 床層流動與萃取模型。
2. 推導對應的 1-D 圓柱模型與 1-D truncated-cone 模型（以截面積 A(z) 修正），與 CFD 對照。
3. 以 two-grain（fines + boulders）first-order mass transfer 擬合 fine / coarse 兩種研磨的出口濃度，相較 single-grain 明顯改善。
4. 顯示圓錐床（apex 60°，類 pour-over 幾何）的流場明顯偏離 1-D，最大速度出現在出口與錐壁交角；出口濃度曲線與圓柱相近，但床內萃取分布差異大。
5. 在 brewing control chart 上加入床內 extraction yield 標準差（error bar），提出「extraction uniformity」作為品質指標。

**Methodology**
- 流動：穩態、飽和、固相速度為零、固相體積分率固定；Gidaspow drag（α_s < 0.8 時用 Ergun 型式，第一項為 Kozeny-Carman）。作者指出在此速度範圍「close to Darcy's law」。1-D 模型中 Darcy 的 permeability k_sl 與 drag 係數 K_sl 有對應關係（Eq. 16）。
- 萃取：grain 相濃度 c_s 與孔隙液相濃度 c_l 間 first-order 交換，係數 h_sl，界面面積 A_i 由球形假設的 surface-to-volume 比算出（Eq. 7）；初始濃度由 φ_0、intragranular porosity φ_v = 0.56、true density 1400 kg/m³ 決定（Eq. 12）。fine/coarse 的 φ_0 分別為 0.143 / 0.122。
- 液相擴散忽略（advection dominated），入口濃度為零，初始床已完全濕潤。
- **PSD 如何進入**：Table 1 給 measured PSD 摘要（fine：d32 = 27.34 μm、d43 = 457.84 μm、<100 μm 體積分率 25.52%；coarse：d32 = 37.78 μm、d43 = 823.02 μm、15.08%）。但進入方程的 grain size 是 **擬合值**：「The representative grain diameter is selected to ensure the pressure drop across the bed matches the liquid velocity. In the case of two grain sizes, one grain size is fixed from the particle size distribution and the other is used to fit the experimentally observed pressure drop.」也可改為固定粒徑、擬合液相體積分率。Table 2 的 d_s、α_s、h_sl 皆為各研磨分別設定（例：fine single-grain d_s = 3.1823e-5 m、α_s = 0.8；fine two-grain small/large d_s = 2.517e-5 / 5.63e-4 m）。
- 擬合 vs 量測：mass transfer coefficients h_sl 以 1-D 模型擬合後套用到 CFD；permeability 尺度（代表粒徑或孔隙率）以量測壓降校準，每個研磨各自校準。
- 幾何：圓柱 brewing chamber 內徑 59 mm（axisymmetric，4k cells）；truncated cone apex 60°、截頭半徑 R = 0.018 m，床高依同體積換算（~24k cells，GCI 研究 p = 1.85）。
- 數值：Fluent transient implicit，Δt = 0.05 s，SIMPLE；1-D 用 MATLAB ode23s + method of lines。

**Experiments**
- 量測：Philips Research（Eindhoven）圓柱 brewing chamber，定流量 250 ml/min，60 g 乾粉，總水量約 1 L，水溫 90 °C；量壓降（Bronkhorst P-502C）、流量（CORI-FLOW）、出口濃度（Atago PAL3 Brix 計，1 °Brix = 8.25 g/L）。
- 研磨：2 種（fine：Jacobs Krönung drip-filter grind；coarse：Illy 豆以 Cimbali 磨豆機 #20）。PSD 圖（Fig 3）的量測儀器未在正文說明。
- 驗證類型：**calibration**。壓降：fine 實驗 2.3 bar，CFD 2.319 bar、1-D 2.3 bar（1-D 用來擬合）；coarse 實驗 0.65 bar，CFD 0.657 bar。出口濃度 RMSE（1-D）：fine single→two grain 7.80 → 5.81 kg/m³；coarse 11.65 → 6.23 kg/m³。
- 圓錐 case 為**純模擬**（無實驗）：1-D 錐模型壓降 fine 7.35 bar / coarse 1.63 bar，CFD 8.4 / 1.89 bar。
- control chart：fine grind 在目標區間內床內 EY 變異約 5 個百分點；coarse 變異小。

**Limitations**
- 作者承認：床完全飽和、不含 infiltration；液相體積分率固定（不考慮 consolidation、溶解、膨潤）；permeability 空間均勻；初始所有可溶物已溶於孔隙導致初期濃度高於理論飽和；球形顆粒假設；1-D 錐模型只對小錐角準確。
- 讀者觀察：
  - 定流量操作（pump 驅動），不是重力排水；無 V_out(t) 或 drain time 的預測，壓降是唯一流動觀測量，且每個研磨各自校準一次。
  - 兩研磨的 d32 只差約 1.4 倍（27 vs 38 μm），但壓降差約 3.5 倍（2.3 vs 0.65 bar）；文中未檢驗 d32-based Kozeny-Carman 能否在兩研磨間直接傳遞，而是以擬合粒徑吸收。
  - 圓錐（pour-over）幾何仍是滿床、定流量、無自由液面，與 V60 實際（間歇注水、液面變化、排空）差距大。
  - 作者自述實驗條件「typical of an espresso extraction」的裝置，但劑量與水量接近 drip filter。

**Relevance to the candidate claim**
- **不支持也不否定**「measured PSD → 不重擬合跨研磨預測流動」：本文明確採用「每研磨一個代表粒徑以擬合壓降」，即 permeability 是 per-grind 校準，而非由 PSD 預測。
- 重疊處：Kozeny-Carman 型 permeability、bimodal PSD 的 two-grain 表示、fines (<100 μm) 分率、錐形幾何的 1-D 截面積修正（與本專案的 V60 錐形 reduced-order 處理直接相關）。
- 不重疊處：無重力驅動排水、無 unsaturated/capillary、無 clogging、無 V_out(t) 時序、無跨研磨 held-out 測試。
- 可作為 claim 的「前人做法基準」：前人以量測壓降逐研磨校準 permeability；若本專案能以單一 closure + measured d32 跨研磨，則是相對於此的增量。另其 Table 1 顯示 d32 與 d43 對研磨的敏感度差異很大，可作為「選 d32 作尺度錨」需要論證的提醒。

**Code & Resources**
- 無程式碼連結。Data availability：「All relevant data are within the manuscript and its Supporting Information files.」S1/S2 Video（control chart 動畫）、S1/S2 Appendix（PDF）。

---

### [@cameron2020] Systematically Improving Espresso: Insights from Mathematical Modeling and Experiment

**Metadata**
- Authors：Michael I. Cameron, Dechen Morisco, Daniel Hofstetter, Erol Uman, Justin Wilkinson, Zachary C. Kennedy, Sean A. Fontenot, William T. Lee, Christopher H. Hendon, Jamie M. Foster
- Year / Venue：2020，Matter 2(3): 631–648
- DOI：10.1016/j.matt.2019.12.019
- 實際讀到的全文來源：University of Huddersfield Pure 存放的 **accepted manuscript**（Manuscript.pdf，11 頁，dated December 11, 2019）。注意：此版本的圖號皆顯示為「Figure ??」，圖本身與 Supplemental Information（參數表、homogenization 推導、9 bar clogging 資料、tamping 資料）**未讀到**；arXiv 上找不到此文的 preprint。正式出版版本可能有排版／文字差異。
- 狀態：peer-reviewed（讀的是 accepted manuscript）

**Problem**
在 espresso 中，研磨度、劑量、水壓如何決定 extraction yield（EY），以及為何實測 EY 對研磨度呈非單調。

**Key Contributions**
1. 以 multiple-scales homogenization 由 pore-scale 方程推導 1-D 宏觀萃取模型（兩粒徑族：fines a1 與 boulders a2，各自解球內擴散）。
2. 提出非線性界面溶解率 G = k c_s (c_s − c_l)(c_sat − c_l)。
3. 實驗顯示 EY 對 grind setting（GS）有峰值：GS < 1.7 時 EY 反而下降，與「均勻流」模型預測的單調遞減（越粗越低）矛盾；作者解讀為細研磨時出現 inhomogeneous / partially clogged flow。
4. 以「降低床面暴露面積」的經驗修正重現細研磨端的下降；據此提出 down-dose + 粗磨的實務方案，並在咖啡館一年銷售資料上估算經濟效益。

**Methodology**
- 微觀：液相 advection-diffusion + Navier-Stokes；顆粒內 Fickian diffusion D_s；界面通量 G（Eq. 16）。等溫假設；起始時床已充滿無溶質的水（不模擬 pre-infusion）。
- 宏觀（homogenized 1-D）：(1−φ_s)∂c_l*/∂t = ∂/∂z(D_eff ∂c_l*/∂z − q c_l*) + bet_1 G_1 + bet_2 G_2；兩族球內擴散方程（Eq. 21–22）；EY 由出口通量積分（Eq. 24）。
- **流動如何決定（關鍵）**：Darcy flux q **不是由 PSD/permeability 預測**，而是由量測的 shot time 反推：q = M_out / (π R0² ρ_out t_shot)（Eq. 26）。文中雖稱「population, surface area, and volume fraction of the particles are used to estimate the permeability of the bed」，但模型實際使用的是 q from shot time。水壓改變時假設 q 與 P_tot 成正比。
- **PSD 如何進入**：Beckman Coulter LS13 320 雷射繞射量測 PSD；由 PSD 推出兩族粒徑 a1、a2 與其單位體積界面面積 bet_1、bet_2（假設均勻分布於床中）；觀察到研磨變細時 fines 比例上升但 fines 尺寸不變。N2 physisorption 顯示無 microporosity（BET 無法線性擬合，故不報 BET 值）。
- 床固相體積分率 φ_s = 0.8272（取自 Moroney 等人），床高由劑量、密度、半徑決定，假設與研磨無關。
- 擬合參數：D_s = 6.25×10⁻¹⁰ m²/s、k = 6×10⁻⁷ m⁷ kg⁻² s⁻¹；D_eff 設為小值（advection 主導，並以尺度估計論證）。

**Experiments**
- 地點與設備：Frisky Goat Espresso（Brisbane）；San Remo Opera 三孔機、20 g ridgeless basket；Mahlkönig EK43；Puqpress 自動壓粉（98 N，精度 ±3 N）；Acaia Lunar 秤；溫度 92 °C。
- 配方：20.0(5) g 進、40.0(5) g 出；9 bar 時細研磨出現 clogging，改用 6 bar。tamp 壓力在其測試範圍內對 shot time 與 EY 無明顯影響。
- 樣本數：校準量測 n = 20，其餘五重複（pentaplicate）。研磨點數由圖可見（文中提到 GS 1.1、1.3、1.5、1.7、2.0、2.3 等），但精確點數因圖未讀到無法確認。
- 結果：shot time 對 GS 為線性（越粗越短）。GS < 1.7 時 EY 下降；以「部分床乾燥無流動」極端假設，模型與實驗的 EY 差距在 GS = 1.1、1.3、1.5 分別為 13.1%、6.1%、2.6%。EY 22% 可由 GS ≈ 1.3 或 2.0 兩種設定達成。
- 驗證類型：D_s、k 為 **calibration**（擬合）；均勻流區（GS ≥ 1.7）宣稱「faithfully reproduce」，但流量本身是由每個研磨的量測 shot time 輸入，**非 held-out 流動預測**。細研磨端以經驗修正「performed empirically until our predicted EY matched」。
- 經濟：咖啡館 2018-09 至 2019 共 27,850 杯；每杯省 $0.13、年省 $3,620；外推全美每日 $3.1 M、每年 $1.1 B。

**Limitations**
- 作者承認：等溫；不模擬 wetting/pre-infusion；假設均勻流（在細研磨端失效）；飲品密度取水；床高不隨研磨變；clogging 修正為經驗式且無床內實際地圖；EY 不等於風味。
- 讀者觀察：
  - **流量是輸入而非輸出**：q 由各研磨的實測 shot time 決定，因此本文的「預測」只在萃取端；流動／排水時間的跨研磨預測完全不在本文範圍。
  - 細研磨端的「clogging」只是以縮減暴露面積的自由參數吸收，不是由 PSD 推導的 clogging closure。
  - 兩族粒徑表示把 PSD 壓縮為 2 個尺度，無 bin-resolved。
  - accepted manuscript 中圖與 SI 不可得，參數完整表無法核對。

**Relevance to the candidate claim**
- 對 claim 的直接意義：**本文沒有做「PSD → permeability → flow」的預測**；它把每個研磨的流量當作量測輸入。因此它不是 claim 的先例，也不構成競爭。
- 但它提供了重要的反證風險：在 espresso 細研磨端，均勻 Darcy 流假設失效（EY 非單調、9 bar 時 clogging），提示「單一 permeability closure 跨研磨」在 fines 多的一端可能系統性失敗；本專案的 throat/deposition clogging 拆分正是針對此端，需要在最細研磨點特別檢驗。
- 重疊：bimodal PSD、fines 比例隨研磨上升而 fines 尺寸不變的觀察（與以 d32 作尺度錨相關：fines 數量增加會拉低 d32）、雷射繞射 PSD。
- 不重疊：espresso（6 bar 泵壓、20 g、~數十秒）vs V60 重力排水；無 V_out(t)、無 drain time、無 capillary retention、無熱模型。

**Code & Resources**
- 無程式碼連結。實驗資料在正文圖中；參數表在 Supplemental Information（未讀）。accepted manuscript：https://pure.hud.ac.uk/ws/portalfiles/portal/18815501/Manuscript.pdf

---

### [@foster2025] Dynamics of liquid infiltration into an espresso bed using time-resolved micro-computed tomography: Insights from experiment and modeling

**Metadata**
- Authors：Jamie Foster, William Lee, Kevin Moroney, Dimitri Prjamkov, Michael Salamon, Ann Smith, Joseph Petrassem-de-Sousa, Michael Vynnycky
- Year / Venue：2025，Physics of Fluids 37, 013383（Special Topic: Kitchen Flows 2024；submitted 2024-10-24，accepted 2024-12-26，online 2025-01-28）
- DOI：10.1063/5.0245167
- 實際讀到的全文來源：University of Limerick Research Repository 的出版版 PDF（22 頁，CC BY-NC 4.0，含 Appendix A–C）。方程式由 PDF 轉文字，符號有部分亂碼，結構與參數表可辨識。
- 狀態：peer-reviewed

**Problem**
espresso 沖煮初期水滲入乾燥咖啡床的 infiltration 動態（濕潤前緣位置與頭部空間積水）為何，能否以含泵特性的 1-D sharp-front 不飽和流模型重現。

**Key Contributions**
1. 首次以 rotating x-ray system（ROXS，1000 fps、1 rotation/s，每秒一個重建）時間解析 micro-CT 追蹤 espresso 床的濕潤前緣 s(t) 與頭部空間液面 H(t)。
2. 前緣位置以 sigmoid 組合函數（Eq. 1）擬合吸收剖面抽取；分 10 個徑向殼層分析，fine grind 的前緣近似平坦均勻。
3. 提出 1-D Green-Ampt 型 sharp-front 模型，耦合二次型泵特性曲線、管路阻力、頭部空間受困氣體理想氣體壓縮，分 pre-ponding / post-ponding / post-saturation 三階段。
4. 模型顯示 infiltration 期間流量非定值：ponding 後約一秒內降到初值約五分之一再回升，即「流量極小值」可僅由泵與頭部空間動態產生，而不需 extraction、degassing 或顆粒重排機制。

**Methodology**
- 泵：p_p = p_m − (p_m − p_a)(Q/Q_m)²；管路 p_p − p_h = R_f Q；頭部空間氣體 p_h = p_a H0 b /(H0 − H)，b = T1/T0（入水加熱受困空氣）。
- 床內：濕區 Darcy q = −(k/μ)(∂p/∂z − ρg)，不可壓縮 → 壓力線性；前緣處 p = p_a − p_c（capillary suction），床頂 p = p_h + ρgH。前緣推進 φ_T ds/dt = q。**二元飽和**（濕／乾），作者明言沒有資料可參數化 permeability–saturation 與 capillary pressure–saturation 關係，故不採連續飽和。
- 無量綱參數：P_m、P_c、Θ（H0/L）、G、R、b、K（無量綱 permeability）、φ_T。
- 擬合：fmincon（interior-point）擬合 φ_T ∈ [0.3, 0.9]、K ∈ [0, 0.2]、t_shift ∈ [0, 1] s，目標函數為 s 與 H 的平方誤差和（Eq. 39）；MultiStart 檢查非局部極小。
- 固定參數（Table I）：L = 9.975 mm、H0 = 7.8 mm（由 CT 影像估）、A = 0.002734 m²（直徑 59 mm）、μ = 0.315×10⁻³ Pa·s、ρ = 965 kg/m³（90 °C 水）、Q_m = 317 ml/min（無 portafilter 實測）、R_f = 3.83×10⁶ Pa·m³/kg（nominal）、p_c = 0.1 bar（nominal，文獻無咖啡床資料）、p_m = 15 bar（製造商）、T0 = 296.15 K、T1 = 363.15 K。
- **PSD 如何進入**：**沒有進入模型**。PSD 只以 micro-CT 截面定性描述（coarse 主要 300–1000 μm，fine 低於 300 μm）；permeability 完全由擬合 K 得到。

**Experiments**
- 設備：Fraunhofer EZRT ROXS（160 kV、5 mA，XEye HS 偵測器 1024×1024、200 μm pixel spacing、2000 fps 上限）；DeLonghi EC685 Dedica（移除金屬件以改善重建）；Demoka Minimoka GR 0203 磨豆機；100% Arabica。
- 樣本：2 種研磨（fine、coarse），各 10 g、手動壓粉至秤上讀 12 kg；30 s 內 30,000 projections → 30 個 1 s 重建。**各研磨各一次沖煮**（文中未提重複）。
- 只對 **fine grind** 做模型擬合；coarse 的濕潤前緣較快且不均（靠壁處較快），作者判定 1-D 化過度簡化，未建模。fine grind 前緣分析取 5 條垂直線。
- 結果（fine）：t_shift = 0.796 s，ponding 在 t = 0.823 s，床飽和於 t = 6.669 s；φ_T = 0.322（作者認為偏低，預期 0.4–0.6）；K = 0.0495 對應 k = 2.97×10⁻¹⁵ m²，作者稱與文獻值一致。s(t) 形狀擬合良好；H(t) 形狀正確但模型上升略快。未報告數值化的擬合誤差指標（如 RMSE）。
- 敏感度：φ_T、K、P_m、b 影響大；P_c 與 R 在測試範圍內影響小。
- 驗證類型：**calibration**（單一研磨、單一沖煮的擬合），無 held-out。

**Limitations**
- 作者承認：sharp front 與 1-D 假設（coarse 不成立）；二元飽和；p_c 缺資料；R_f 無法量測；不含溶質傳輸、CO2 exsolution、顆粒內孔吸水與膨潤；溫度對 infiltration 影響未納入；床頂固定不考慮膨脹／壓縮；實驗起始時間不確定（需 t_shift）。
- 讀者觀察：
  - 僅 1 個研磨被建模、每研磨 1 次沖煮，無法評估跨研磨可傳遞性或重複性。
  - 擬合值 φ_T 偏低，可能是在吸收未建模機制（作者提到延遲濕潤或封閉孔），表示 K 與 φ_T 可能有共變。
  - capillary p_c 在 espresso 泵壓下被證明不敏感，但在 V60 重力驅動（數 cm 水頭）下 capillary 項相對量級完全不同，此結論不可外推。

**Relevance to the candidate claim**
- **不支持** claim 的預測性部分：permeability 是由 CT 前緣資料擬合，而非由 PSD 預測；只做一個研磨。
- 有價值的重疊：
  - 直接觀測到「coarse 研磨濕潤前緣不均、靠壁較快」，這是 preferential flow / wall effect 的實驗證據，對 V60 的 bypass 與錐壁效應有參考意義。
  - 明確論證 infiltration 期間的流量極小值可由「驅動端動態」造成；對應到 V60，注水率斷點與液面變化對 V_out(t) 早段形狀的影響應先由驅動端（注水 V_in(t)、液位）解釋，再考慮床內機制。這支持本專案「注水衝擊／wetting 階段」需要顯式處理而不是塞進 k。
  - Darcy + capillary suction at front 的 Green-Ampt 結構與本專案 capillary support/cutoff closure 屬同類。
- 不重疊：espresso 泵驅動、無排水期、無 V_out(t) 與 drain time、無萃取、無熱、無 PSD。

**Code & Resources**
- 無程式碼。Data availability：「available from the corresponding author upon reasonable request」。數值以 MATLAB ode23s / fmincon / MultiStart 求解。開放全文：https://doi.org/10.34961/researchrepository-ul.28322306

---

### [@lee2023] Uneven extraction in coffee brewing

**Metadata**
- Authors：W. T. Lee, A. Smith, A. Arshad
- Year / Venue：2023，Physics of Fluids 35(5): 054110
- DOI：10.1063/5.0138998
- 實際讀到的全文來源：arXiv:2206.12373v2（physics.flu-dyn，v2 dated 2023-04-07／10 April 2023，6 頁）。正式出版版未讀；arXiv 版與出版版可能有細節差異。
- 狀態：arXiv preprint（v2，已於 PoF 出版；讀的是 preprint 版）

**Problem**
Cameron et al. (2020) 觀察到的「研磨越細 EY 反而下降」，能否由 flow 與 dissolution 的正回饋（溶解 → 孔隙率上升 → permeability 上升 → 更多流量）造成的不均勻萃取來解釋。

**Key Contributions**
1. 提出最簡的 two-pathway 模型：床橫向分成兩個等體積、等截面積的平行通道，總流量 Q 固定，依 Kozeny-Carman permeability 比例分流。
2. 溶解改變孔隙率（假設可溶與不可溶部分密度相同，EY 與 ε 直接對應），形成 reaction-infiltration 型正回饋，初始小孔隙率差 δ 被放大。
3. 擬合 Cameron 資料後重現 EY 對研磨度的峰值；結論是不均勻流在**所有研磨**都存在，EY 下降的轉折對應「其中一條通道的可溶物完全耗盡」，而非不均勻流的起始。

**Methodology**
- 分流：Q_{1,2} = Q κ_{1,2}/(κ_1 + κ_2)，κ_i = ε_i³/(1 − ε_i)²（無量綱 Kozeny-Carman）。
- 總流量 Q **由量測的 shot time 給定**：Q = M_shot/(ρ_w t_shot)，t_shot 以 Cameron 資料線性擬合 t_shot = a0 + a1 g（a0 = 50.5 s，a1 = −11.5 s）。
- 萃取：transfer term D S (c_sat − c)/λ（單一粒徑尺度，follow Moroney 2015），Heaviside 截斷 EY_max；每通道內孔隙率與濃度均勻（無垂直分層）。
- 表面積 S 對研磨度線性擬合：S = b0 + b1 g（b0 = 0.543 m²，b1 = −0.112 m²），由 Cameron 的 fines/boulders 表面積資料組合。
- **PSD 如何進入**：只透過 S(g) 的線性擬合間接進入；Kozeny-Carman 中沒有粒徑，只用於兩通道間的相對分流；作者明言單一 transfer term 隱含 unimodal 假設。
- 參數（Table I）：M_shot = 0.04 kg、ρ_w = 997 kg/m³、ε0 = 0.173、c_sat = 212.4 kg/m³、ρ_c 文獻值 399 kg/m³ 但**強制使用 798 kg/m³（作者稱 unphysical）**、α = 3.76；擬合：λ/D = 0.125×10⁶ s/m、δ = 0.035、EY_max = 33.8%。
- 擬合方法：constrained BFGS 最小化 Σ(EY_model − EY_data)²（跨研磨），RK4 adaptive 積分。

**Experiments**
- 無自有實驗；使用 Cameron et al. (2020) 的 EY vs grind setting g（約 g = 1.1–2.3）與 shot time 資料。
- 結果：qualitative 重現峰值；g = 1.1 時通道 1 在 τ ≈ 0.8 耗盡可溶物；g = 2.3 時孔隙率差持續增長但兩通道皆未耗盡。擬合 λ/D 與由 Moroney 2015 參數算出的 0.128×10⁶、0.210×10⁶ s/m 同量級；EY_max = 33.8% 對照 Smith & Lee 由他人資料算出的 30.3%。
- 未報告量化擬合誤差指標。
- 驗證類型：**calibration**（3 個參數 + 1 個人為加倍的 ρ_c 對同一組 EY 資料擬合），無 held-out。

**Limitations**
- 作者承認：使用文獻 ρ_c 時 EY 在臨界研磨以下只會持平而不下降，必須用兩倍的 unphysical ρ_c；δ 偏大（相對 ε0 = 0.173）；無 bimodal、無垂直分層、兩通道等權；相同 δ 用於所有研磨，因此模型不支持「clogging 起始造成轉折」的解釋。
- 讀者觀察：
  - 流量完全由 shot time 外部給定；Kozeny-Carman 不用於預測總流量，只用於分流比。
  - 模型與 Cameron 原文的 clogging 解釋只是不同的擬合敘事，兩者都沒有獨立觀測（例如床內 CT 或分區出流）判別。

**Relevance to the candidate claim**
- **不支持** claim：總流量由實測 shot time 給定，並非由 PSD 預測。
- 但提出一個與 claim 相關的機制性風險：若溶解造成的孔隙率／permeability 時變在 V60 中顯著，則「單一靜態 permeability closure」在長沖煮時間下會出現系統偏差。對 V60（萃取量級的質量損失、低泵壓、重力驅動），這種 reaction-infiltration 正回饋量級需另估；本專案的 wetbed / clogging 狀態可對照此機制檢查是否已涵蓋。
- 重疊：Kozeny-Carman ε³/(1−ε)² 形式、lateral 不均勻流（與 bypass／preferential-flow closure 相關）。
- 不重疊：espresso、固定總流量、無 V_out(t)、無 drain time、無 capillary、無 measured PSD bins。

**Code & Resources**
- arXiv ancillary files：`coffee_odes.wxmx`（wxMaxima 推導與無量綱化）、`parameter_fitting.m`（Octave 最小平方擬合）、`latex_output.m`；見 https://arxiv.org/src/2206.12373v2/anc
- preprint：https://arxiv.org/abs/2206.12373

---

## 對 candidate claim 的綜合判讀

- 四篇中**沒有任何一篇**由 measured PSD 預測跨研磨的流量或排水時間：Moroney 2019 以量測壓降逐研磨擬合代表粒徑；Cameron 2020 與 Lee 2023 直接把量測 shot time 當作流量輸入；Foster 2025 以 CT 前緣擬合 permeability，且只建模一個研磨。
- 四篇皆為 espresso 或 pump-driven 定流量／高壓裝置；Moroney 2019 是唯一涉及錐形（pour-over 類）幾何者，但只有模擬，沒有實驗，且是滿床定流量。
- 對 claim 不利的訊號：Cameron 2020 的細研磨 EY 非單調與 9 bar clogging、Foster 2025 的 coarse 研磨前緣不均、Lee 2023 的溶解－permeability 正回饋，都指出單一靜態 permeability closure 在研磨範圍兩端可能失效。

# Phase 3 deep-dive notes C：permeability、PSD 與平衡萃取

檢驗的候選主張：「measured PSD 加上單一 permeability closure，不需重新擬合，就能跨研磨度預測 V_out(t) 與 drain time」。

全文來源總覽：

| Paper | 實際讀到的內容 |
|---|---|
| Corrochano 2015 (JFE) | **期刊全文沒讀到**（ScienceDirect 回 403；Birmingham Pure 的 accepted manuscript 擋在 Cloudflare challenge 後面，沒有繞過）。讀了第一作者 EngD thesis 全文（Roman Corrochano 2017，Univ. Birmingham eTheses 7176）的 Ch.3 §3.3.16、§3.4.3、Ch.4 Table 4.1/4.2、Ch.6 全章，thesis 把這篇 JFE 列為自己的 publication。期刊 abstract 取自 Birmingham Pure 的搜尋摘要。 |
| Mo 2023 (Sci Rep) | 全文（nature.com open access HTML），含 Table 1–5 |
| Liang 2021 (Sci Rep) | 全文（nature.com open access HTML）；Supplementary 沒讀 |
| Smrke 2024 (Sci Rep) | 全文（nature.com open access HTML）；Supplementary 沒讀；Fig. 5 的回歸品質數字只在圖內，文字沒寫 |

---

### [@corrochano2015permeability] A new methodology to estimate the steady-state permeability of roast and ground coffee in packed beds

**Metadata**
- Authors：B. R. Corrochano, J. R. Melrose, A. C. Bentley, P. J. Fryer, S. Bakalis
- Year / Venue：2015，*Journal of Food Engineering* 150, 106–116
- DOI：10.1016/j.jfoodeng.2014.11.006
- 讀到的全文：**期刊版只讀到 abstract**。方法與數據來自 thesis：B. Roman Corrochano (2017), *Advancing the engineering understanding of coffee extraction*, EngD thesis, University of Birmingham（https://etheses.bham.ac.uk/id/eprint/7176/），Ch.3 §3.3.16 / §3.4.3、Ch.4 Table 4.1–4.2、Ch.6。thesis 的 Publications 頁把這篇 JFE 列為本人著作。以下數字都來自 thesis，可能和期刊版的數值或篇幅不同。例如 Mo 2023 引用本文時寫的範圍是 2.59×10⁻¹⁴–3.36×10⁻¹³ m²，和 thesis Table 6.1 的最小值與文字敘述一致。
- Peer-reviewed：是（期刊）；thesis 經過學位審查

**Problem**
espresso 型 coffee packed bed 的 steady-state permeability 缺少可重複的量測方法，也不清楚 Kozeny–Carman 能否從 PSD 預測它。

**Key Contributions**
1. 用自製 extraction rig 先 hydrate 600 s 到 steady state，再把 tank 靜水壓從 4.5×10⁵ Pa 每次降 0.5×10⁵ Pa 降到 0.5×10⁵ Pa。每一階記錄 60 s，取最後 30 s 的平均 Q–ΔP，fit Darcy 求 κ。
2. 系統量測 4 個 espresso grinds（ΨB–ΨE）× 3 個初始 bed density（360/400/480 kg m⁻³）的 κ，另外量了 flaked coffee、溫度（15 vs 80 °C）、aspect ratio（2:1 vs 6:1）。
3. 量化 bed 在流動下的 consolidation（高度減少 0–31%），並把它當成 κ 偏離 KC 的主因之一。
4. 比較兩個 Kozeny–Carman 型模型和量測值：dry d[3,2] 的 KC 系統性高估 κ；在 tortuosity power law 裡逐 grind 擬合 exponent n 才 fit 得好。

**Methodology**
- Darcy：ΔP_bed = Q L μ / (κ A)（Eq. 3.20），L 用 consolidation 修正後的 steady-state bed 長度。ΔP_bed = P_trans − ΔP_elements（扣除 cell 元件壓損）。
- Model 1（KC + sphericity + Sauter）：κ = (Φ d[3,2])² ε³ / [180 (1−ε)²]（Eq. 3.41）。**PSD 透過 Sauter d[3,2] 進入**，再乘上量測的 sphericity Φ（QICPIC 影像量測）。
- Model 2：在一般式 κ = ε³ / [2 τ² S_v² (1−ε)²] 代入 τ = (1/ε)ⁿ（Dias et al. 2006，n 的文獻值 0.4 為 loose、0.5 為 dense bimodal spheres），得到 κ = (Φ d[3,2])² ε³ / [72 (1/ε)^{2n} (1−ε)²]（Eq. 3.43）。
- ε_bed 由 intrinsic density、particle porosity（ε_particle，量測值 0.50–0.57，或四 grind 平均 0.53）、bed density 推算，再依 consolidation 修正。**ε 不是直接量測**。
- PSD 量測：laser diffraction。dry 用 Sympatec HELOS + RODOS/M，wet 用 Malvern Mastersizer 2000。dry d[3,2]：ΨB 79.7、ΨC 101.6、ΨD 112.9、ΨE 131.4 μm。wet d[3,2]：22.3、28.3、38.6、37.0 μm，wet 法會偵測到 1–10 μm 的顆粒與油滴，所以小很多。
- 擬合 vs 量測：κ 從 Q–ΔP 斜率擬合（每組 R² > 0.97）；d[3,2]、Φ、ε_particle 為量測或推算；Model 2 的 n 為**逐 grind 擬合**。
- Re_p（以 R_pore = Φ d[3,2] ε / [3(1−ε)] 為長度尺度）0.04–4，作者據此判定屬 Darcy regime。

**Experiments**
- 4 grinds（ΨB–ΨE，同一 Blend 1）× 3 bed density × 每組 3 個獨立樣本；80 °C；2:1 brewing chamber（V = 20 cm³，A = 1.1×10⁻³ m²）。
- Table 6.1 κ（m²）：ΨB 7.7e-14 / 4.9e-14 / 2.6e-14；ΨC 1.4e-13 / 1.2e-13 / 4.9e-14；ΨD 2.4e-13 / 1.9e-13 / 6.4e-14；ΨE 3.4e-13 / 4.4e-13 / 9.0e-14（依序為 360/400/480 kg m⁻³）。文字寫的範圍是 2.6×10⁻¹⁴–3.4×10⁻¹³ m²。期刊 abstract 寫 10⁻¹³–10⁻¹⁴ m²。
- 全資料最大/最小 κ 比 13。bed density 增加約 30%（360→480），κ 降 3–4 倍。ρ=360 時 κ(ΨE)/κ(ΨB) = 4.4，ρ=480 時為 3.4。
- consolidation：0%（ΨE，480）到 31%（ΨB，360），主要發生在前 20–30 s。
- 驗證類型：**calibration / comparison，不是 blind prediction**。
  - Model 1，dry d[3,2]，平均 ε_particle：全部高估。相對誤差隨 grind 變粗而變大，ΨB 30%、ΨE 520%。
  - Model 2，n = 0.5：ΨE 誤差 340%；ΨB、ΨC 低估，ΨD、ΨE 高估。
  - Model 2 逐 grind 擬合 n：ΨB 0.27、ΨC 0.33、ΨD 0.64、ΨE 1.01（R² 0.81–0.98），對應 KC prefactor 189–1330（標準值為 180）。
  - 換成 wet d[3,2] 會大幅低估 κ，dry d[3,2] 則高估。
- 溫度：ΨB 在 15 °C 的 κ 約為 80 °C 的 6 倍。作者用 consolidation 不同（16% vs 25%）解釋，KC 算出的理論比值是 5.3。
- aspect ratio：ΨB 在 6:1 和 2:1 的 κ 比約 3（無 consolidation 時 KC 理論比值 10.6）；ΨE 兩者相當。
- 非穩態：Q(t) 先在 20–30 s 內降到最小，30–80 s 回升，之後約 500 s 大致穩定。ΨB 在高 density 時有暫時斷流約 20 s。

**Limitations**
- 作者承認的：
  - KC 假設 mono-sized spheres，不適用連續 bimodal PSD。
  - consolidation 不能只當成 ε 下降處理。
  - κ 對 ε_particle 與 d[3,2]（dry 或 wet）極敏感。
  - bed 結構與粒徑「process-history dependent」，會受 tamping force、可溶團塊溶解、fines 流失與漂浮影響。
  - consolidation 的量測法本身有 1.2–2.3 倍的不一致。
- 讀者觀察：
  - 「good fit」靠的是**每個 grind 各擬合一個 n**，等於每個研磨度都重新擬合，不支持「單一 closure 跨研磨度預測」。
  - κ 量在 600 s 後**已完全萃取**的 bed 上，是 forced flow 0.5–4.5 bar 的 espresso 幾何，不是 gravity-driven 的 V60。
  - ε 是推算值，不是量測值。
  - 只有一個 blend，4 個 grinds。

**Relevance to the candidate claim**
- 這篇是直接的**反證**：dry laser-diffraction d[3,2] 代入 KC 不能跨 grind 預測 κ，誤差 30%（細）到 520%（粗），而且誤差隨 grind 系統性變化，不是常數倍率。所以只校一個 prefactor 不夠，至少需要 grind-dependent 的 tortuosity exponent（n 0.27→1.01）。
- 同一 grind 改變 packing（bed density ±30%）時 κ 變 3–4 倍，可見 κ 被 packing／consolidation 主導的程度不亞於 PSD。
- 對 V60 的意涵：
  - 我方模型以 Sauter d32 為尺度錨，方向與本文一致（作者也認為 d[3,2] 是水力相關尺度）。
  - 但本文顯示 d32 加 KC 的跨 grind 誤差可到數倍，所以主張要成立，必須用我方自己的跨 grind 盲測數據證明。
  - dry-vs-wet d[3,2] 差 3–4 倍，提醒我們 image-analysis PSD 的 d32 會受偵測下限影響（對應 AGENTS.md 的 `censored` 欄位與 resolution bound）。
- 方法差異：espresso、forced flow、steady state、已萃取 bed，誤差是 κ 的相對誤差；本文**沒有**做 V_out(t) 或 drain time 的預測。

**Code & Resources**
- 無 code 或 data repo。
- Thesis PDF：https://etheses.bham.ac.uk/id/eprint/7176/2/Roman-Corrochano17EngD.pdf
- Accepted manuscript（Cloudflare 擋住，未讀）：https://research.birmingham.ac.uk/files/18167003/Corrochano_et_al_New_methodology_estimate_Journal_Food_Engineering_2015.pdf
- 延伸線索（未讀）：Strathclyde 的 "A model for the permeability of coffee pucks validated using X-ray computed micro-tomography"（https://strathprints.strath.ac.uk/95930/）

---

### [@mo2023microct] Exploring the link between coffee matrix microstructure and flow properties using combined X-ray microtomography and smoothed particle hydrodynamics simulations

**Metadata**
- Authors：C. Mo, R. Johnston, L. Navarini, F. Suggi Liverani, M. Ellero
- Year / Venue：2023，*Scientific Reports* 13, 16374
- DOI：10.1038/s41598-023-42380-y
- 讀到的全文：nature.com open-access HTML 全文，含 Table 1–5（另有 arXiv 2305.03911，未讀）。Supplementary（SPH 細節）未讀。
- Peer-reviewed：是

**Problem**
用 microCT 重建真實 coffee matrix 的 3D 結構，再以 SPH 模擬，直接求 permeability 與 tortuosity，並解釋文獻 κ 值為何彼此不一致。

**Key Contributions**
1. 由 microCT（voxel 16.8 μm）建立 SPH digital twin，模擬 percolation，計算 κ 與 tortuosity。
2. 指出在 espresso 壓力梯度下 inertial（Forchheimer）效應顯著，可解釋「壓力越高，Darcy κ 越低」的文獻現象，不必全部歸因於 bed 變形。
3. 比較 4 種研磨度的 κ：平均 κ 隨研磨變粗而上升，但同一 bed 內各子樣本的 κ 變異極大，且越粗變異越大。
4. 萃取後 microCT 顯示孔隙率由出口（底）往入口（頂）遞減，作者用 pressure-dependent erosion 模型解釋。

**Methodology**
- 流動：Darcy ∇P = −(μ/k) q（Eq. 1）；Forchheimer ∇P = −(μ/k) q − (ρ/k₁)|q|q（Eq. 2）。tortuosity 由 SPH 粒子軌跡計算（Eq. 3），並與 τ = (1/ε)ⁿ（Eq. 4）比較。
- 幾何：microCT 二值化。灰階雙峰不明顯，作者**以匹配文獻典型 bed porosity 0.17 來決定 threshold**，所以 ε 是假設值，不是量測值。cuboid 樣本 600³ voxels（1 cm³）；SPH 子域約 708 μm 見方（L_y 991 μm），周期邊界，以 body force 驅動。
- PSD：laser diffraction（Malvern Mastersizer 3000）；Table 1 列出 d[3,2]、d[4,3]、specific surface、<100 μm 體積分率。**PSD 不進任何 closure**，κ 直接由幾何模擬求得。全文**沒有做 Kozeny–Carman 比較**。Re 以 d[4,3] 為特徵長度。
- 擬合：模擬得到的 q–∇P 曲線 fit Darcy 或 Forchheimer，得 k^D、k^F、k₁^F。

**Experiments**
- 粉種：同一 medium-roast arabica blend 的 4 種研磨（E espresso、H capsule、M moka、F drip filter），H 另有 dark roast。均裝在 illy Iperespresso capsule（約 14.6 mm 高 × 32.5 mm 寬，6.7±0.1 g）。
- Table 1：d[3,2] E 81.0、H 90.1、M 116、F 214 μm；d[4,3] 308、341.6、372、673 μm；<100 μm 體積分率 29.21、27.52、20.26、9.7%。
- Type H 單一樣本（ε 0.17）：Darcy k = 5.51×10⁻¹³ m²；高梯度（50–400 bar/m）時 Darcy k 由約 5.2 降到 2.5×10⁻¹³ m²。Forchheimer fit 得 k = 8.0×10⁻¹³、k₁ = 2.17×10⁻¹³ m²；Re（d[4,3]）0.84–3.86；τ = 1.80，n = 0.33。
- 每種粉 6 個子樣本，k^D（10⁻¹³ m²）：
  - H：2.58–35.1，ε 0.162–0.226
  - E：0–27.6，ε 0.131–0.204，其中一個樣本 k = 0（ε 0.131）
  - M：1.74–38.5
  - F：1.19–66.6
  - 同一粉內 k 跨約 1–2 個數量級，與局部 ε 強相關。
- 驗證類型：**純模擬，沒有用該批粉的實測流量驗證**，只和文獻 κ 值比量級。作者明說研磨度與 κ 的連結只做了**定性**分析，因為計算資源不足以模擬全尺寸 bed。

**Limitations**
- 作者承認的：
  - 只能模擬小樣本，無法建立定量關係。
  - microCT 解析度與 fines 及顆粒內孔同量級，分割有困難。
  - 萃取後的 wet 影像無法區分液相與固相，因此低估 ε。
- 讀者觀察：
  - ε 由「匹配 0.17」設定，跨粉的 κ 差異有一部分被這個假設綁定。
  - 子樣本 708 μm 只有約 1–2 個 d[4,3] 寬，不足以當 REV，這可以解釋 k 的巨大變異。
  - 樣本為 capsule 中的乾 bed，沒有 hydration、swelling 與 consolidation。
  - 沒有 KC 或 PSD 的 closure 測試。

**Relevance to the candidate claim**
- 不直接檢驗「PSD 加單一 closure 預測 V_out」，但提供兩個約束：
  1. 平均 κ 隨 d[3,2] 增加、隨 fines 分率減少而上升，方向支持用 d32 當尺度錨。但 E→F 的 d[3,2] 差 2.6 倍，局部 k 變異卻達 1–2 個數量級，所以**局部結構與 packing 的變異遠大於 PSD 的訊號**，在小體積上 PSD 不足以決定 κ。
  2. Forchheimer 修正在 espresso 梯度下很重要。V60 是重力驅動（ΔP 約 10² Pa 量級），Re 應遠低於本文的 0.84–3.86，Darcy 假設可成立，這點對我方是有利的背景。
- 方法為 espresso／capsule 幾何，**沒有任何預測誤差可引用**。

**Code & Resources**
- Data：「available from the corresponding author on reasonable request」。沒有 code repo。
- arXiv preprint：https://arxiv.org/abs/2305.03911

---

### [@liang2021equilibrium] An equilibrium desorption model for the strength and extraction yield of full immersion brewed coffee

**Metadata**
- Authors：J. Liang, K. C. Chan, W. D. Ristenpart
- Year / Venue：2021，*Scientific Reports* 11, 6904
- DOI：10.1038/s41598-021-85787-1
- 讀到的全文：nature.com open-access HTML 全文；Supplementary（PSD 圖 S1、S4、S5）未讀。
- Peer-reviewed：是

**Problem**
用單一 species-averaged 平衡常數，預測 full-immersion 沖煮在平衡時的 TDS 與 extraction yield E。

**Key Contributions**
1. 平衡 desorption 模型：TDS = K E_max / (R_brew + K E_max)（Eq. 11），E = K E_max（Eq. 15），所以 E 與 brew ratio 無關。
2. 實驗證實 TDS ∝ 1/R_brew，E 約 21%，且 K 對溫度（80–99 °C）、研磨度與烘焙度都不敏感。
3. 推導 oven-drying 法量到的 E_oven 會因 spent grounds 保留液而系統性低估：E_oven = K E_max (1 − R_ret/(R_brew + K E_max)) + R_vol（Eq. 22）。
4. 量出 retention ratio R_ret = 2.48 ± 0.19 g 液／g 粉，以及 oven 揮發 R_vol 約 0.023。

**Methodology**
- 一階吸附／脫附 C_A ⇌ C_D，穩態 K = k_D/(k_D + k_A)。**E_max 固定為 0.3**（取自文獻，不擬合），只擬合 K。也報告 lumped 的 K·E_max。
- E 由 TDS 與 R_brew 用 E = TDS/(1−TDS) · R_brew（Eq. 17）計算，不依賴 oven 數據。
- R_ret = R_brew/(1−TDS) − M_brew/M_g（Eq. 24）。
- PSD：Sympatec HELOS/RODOS laser diffraction（R7 lens），三重複；**PSD 不進模型**，只用來報告 median x50 與做相關性分析。沒有 permeability 或 flow 模型。
- 擬合：MATLAB lsqcurvefit（K），nlparci 給 95% CI。

**Experiments**
- 1 L beaker 動態實驗：R_brew 5 與 25 × 80/94/99 °C，三重複。TDS 約 20 min 後趨於平穩（R_brew 5 約 45 min）。R_brew 5 時 TDS 4.07 ± 0.15%，R_brew 25 時 0.75 ± 0.04%，與溫度無關。
- 300 mL 動態實驗：靜置後倒入 Hario V60 03 過濾（drip-out 1–2 min），R_brew 12–20 時 TDS 約 1.65–0.95%。
- 1 L 平衡實驗：Mahlkönig Guatemala grind setting 2–6，median x50 約 580、780、970、1160、1310 μm；溫度 80–99 °C；共 99 個 TDS 值。
  - K = 0.717 ± 0.007（E_max = 0.3），K E_max = 0.215 ± 0.002。TDS 對 1/R_brew 線性，R = 0.999。
  - 平衡 E = 20.70 ± 1.08%（R_brew ≥ 3），模型值 21.5 ± 0.2%。
  - R_brew = 2 不符合模型（低於 R_ret），予以排除。
- 研磨度效應（R_brew 15，99 °C）：TDS 1.36 ± 0.09%，涵蓋 x50 579–1311 μm。TDS 與 E 對 x50 的相關係數分別為 −0.978 與 −0.992，E 範圍約 19–23%。
- Cupping：5 種 Peet's 咖啡（Agtron commercial 54.6–26.9），grind x50 548.3 ± 13.4 μm。caffeinated K = 0.792 ± 0.004、E = 23.9 ± 0.6%；decaf K = 0.726 ± 0.006、E = 22.2 ± 0.4%。四種一般咖啡的烘焙度幾乎無差別。
- 驗證類型：K 是對全部數據的 calibration。「E 與 R_brew、溫度、研磨度無關」是由數據檢驗的模型預測。

**Limitations**
- 作者承認的：
  - 只是 pseudo-equilibrium，不處理動力學。
  - TDS 相同不代表化學組成或風味相同。
  - cupping 的 K 比 1 L 實驗高，原因不明（可能和是否 degas 有關）。
  - 沒有測 cold brew。
- 讀者觀察：
  - E_max = 0.3 假設為「已知」，K 和 E_max 只能以乘積辨識（作者也報告了 lumped 值）。
  - 研磨度範圍 x50 580–1310 μm，偏粗。
  - immersion 平衡與 V60 的 percolation（未達平衡、約 3 min）不同。

**Relevance to the candidate claim**
- **與 V_out(t) 或 permeability 無關**，不能支持或反駁「PSD 預測 drain time」。
- 對我方萃取端有間接支持：
  1. 平衡 E 約 K·E_max，對溫度 80–99 °C 與研磨度不敏感（E 約 19–23%）。這支持把 `max_EY` 當成 roast prior 固定、不放進 fit（AGENTS.md §4 D 級）。注意本文的 E_max 0.3 是假設值，可辨識的是 K·E_max（0.215–0.240，依咖啡而異）。
  2. 溫度只改變動力學，不改變平衡，和我方「溫度只走 Stokes–Einstein D(T)」的設計一致。
  3. R_ret = 2.48 ± 0.19 g/g 是濕粉保留液量的獨立量測，可以當作 V60 最終杯量／capillary retention（`h_cap`、`V_imm`）量級的外部參考。但本文是 immersion 後倒進 V60 自然瀝乾的條件，和 percolation 後的保留可能不同。

**Code & Resources**
- 沒有 code 或 data repo。Supplementary（Table S1 nomenclature、Fig. S1–S5）在出版社頁面。

---

### [@smrke2024fines] The role of fines in espresso extraction dynamics

**Metadata**
- Authors：S. Smrke, M. Eiermann, C. Yeretzian
- Year / Venue：2024，*Scientific Reports* 14, 5612
- DOI：10.1038/s41598-024-55831-x
- 讀到的全文：nature.com open-access HTML 全文。Supplementary（Fig. S1 flow profiles）未讀。Fig. 4、Fig. 5 的係數與 R² 只在圖中，文字沒有寫。
- Peer-reviewed：是

**Problem**
在固定 median 粒徑下，系統性改變 fines 比例（< 100 μm 體積分率），看它如何影響 espresso 流速、萃取時間、萃取率與 headspace VOC。

**Key Contributions**
1. 用加入篩出的 fines（120 μm 篩）在固定研磨設定上獨立改變 Q100μm，把 fines 效應和 median 粒徑 X50 解耦。
2. 證明 fines 增加會降低 bed permeability，使流速下降、萃取時間變長。萃取率與萃取時間落在同一條曲線上，作者因此推論 fines 只改變 permeability，不改變萃取機制。
3. 對整條 PSD 做 PLSR：係數在 <150 μm 為正（延長時間），150–250 μm 約 0，>250 μm 為負。
4. 以 X50 與 Q100μm 的二階多項式回歸預測萃取時間；加入萃取時間後再預測萃取率。

**Methodology**
- 純統計模型：PLSR（R `pls` 2.8-1）與二階 multiple regression。**沒有物理 permeability closure，也沒有 KC**；κ 沒有算出數值，「permeability」是由萃取時間推論的。
- PSD：**Camsizer X2 dual-camera 影像分析**（以投影面積計算的體積加權 X50），每樣本 ≥ 10 g、三次量測。Q100μm 是 <100 μm 的體積分率。
- 擬合 vs 量測：PSD、萃取時間、飲品重量（load cell 動態紀錄）、TDS（VST LAB III，0.45 μm 過濾）都是量測值；迴歸係數為擬合值。

**Experiments**
- 單一 Costa Rica pulped-natural arabica（Colorette 143），Bentwood Vertical 63 研磨機，burr spacing 設定 160、170、180、190、210、250。在 190、210、250 三個設定各加入 1、2、4 g fines（分別配 19、18、16 g 粉，總量 20 g）。共 15 種條件，每種 3 重複。
- espresso：Victoria Arduino Black Eagle，9 bar，20 g 粉手動控制出 40 g 液，20 kgf tamp。萃取時間取機器顯示值。
- 結果：
  - 未加 fines 的樣本，Q100μm 與 burr spacing 呈二階多項式關係；加 fines 後 Q100μm 線性上升，X50 略降。
  - <10 s 與 15 s 的萃取得到 17–18% 萃取率（> 最大值的 80%）。作者認為 > 40 s 已達最大萃取率。
  - X50 與 Q100μm 對萃取時間模型的貢獻顯著，normalized coefficient 大小相近。**文中沒有給出 R² 或預測誤差數值**。
  - 感官上，加 fines 沒有扣分。
- 驗證類型：**in-sample 統計回歸**，沒有 held-out 或跨研磨機驗證。

**Limitations**
- 作者承認的：
  - 只有單一咖啡、單一研磨機。
  - 主峰寬度的影響尚未研究，因為沒有能系統性改變主峰寬度的研磨機。
  - 感官評估只由一位 Q-grader 給 hedonic 分數，不是 double-blind。
- 讀者觀察：
  - 外加的 fines 是篩下物，和研磨時自然產生的 fines 在形狀與分布上可能不同。
  - 沒有量測 ΔP 或 κ，「permeability」只由萃取時間推論。
  - 二階多項式只有 15 種條件，過擬合風險未評估。
  - 研磨尺度是 espresso 的 X50。

**Relevance to the candidate claim**
- 支持「單一尺度不足」：同樣的 X50 在 fines 比例不同時，萃取時間會不同，需要 fines 指標（Q100μm）加 X50 兩個變數，才能以經驗方式預測流動時間。
- 對我方的意涵：
  - Sauter d32 對 fines 很敏感（面積加權），理論上比 median 更能同時反映 fines 與主峰。所以用 d32 當單一尺度錨比 X50 合理，但本文**沒有檢驗 d32**。
  - AGENTS.md 要求 throat clogging（number-based fines）與 deposition clogging（volume-based fines）分開，本文的「fines 只改 permeability、不改萃取機制」結論在方向上支持把 fines 放在水力端。
- 限制：只有 espresso、in-sample 回歸、沒有 κ 數值，所以**不提供 PSD → V_out(t) 預測誤差的可引用數字**。PSD 量測方式（影像分析，Camsizer X2）和我方的 coffeegrindsize 影像法同屬一類，是少數同類方法的文獻。

**Code & Resources**
- 沒有 code repo。Data：「available from the corresponding author on reasonable request」。
