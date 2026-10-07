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
