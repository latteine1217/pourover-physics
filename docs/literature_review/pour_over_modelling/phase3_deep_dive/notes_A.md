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
