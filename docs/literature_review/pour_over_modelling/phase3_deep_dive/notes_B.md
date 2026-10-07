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
