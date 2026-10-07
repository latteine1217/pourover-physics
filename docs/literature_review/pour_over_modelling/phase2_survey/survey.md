# Phase 2 — Survey

Date: 2026-10-07 | Papers in `paper_db.jsonl`: 66（原始去重 868 筆，人工篩選）
Source: OpenAlex（全年份）+ 4 篇以 DOI 補入（Cameron 2020、Uman 2016、Maille 2020、Mo 2023）

## 查詢

Phase 1 七組之外，另跑（全年份）：drip brew extraction model、filter coffee percolation、
coffee percolation porous medium mathematical model、espresso mathematical modelling、
permeability ground coffee packed bed、grinder PSD laser diffraction、coffee particle size image
analysis、desorption model TDS、brewing control chart、fines migration clogging、Ristenpart coffee、
Moroney coffee、SPH coffee、Fasano espresso、coffee filter paper flow resistance、coffee bed
drainage gravity flow、coffee filtration erosion、Kozeny-Carman from grain size、hydraulic
conductivity from PSD、unsaturated gravity drainage outflow、batch brewer、image vs sieve vs laser
diffraction。

**檢索限制**：OpenAlex 全文索引對 J. Food Eng. 等付費期刊摘要覆蓋不完整；Semantic Scholar
被限流未使用；未查 Google Scholar / Scopus。下列「未找到」只代表這組查詢未命中。

## 主題分群

### A. 咖啡萃取的機制模型（espresso / 浸泡 / 一般床層）— 16 篇
- Moroney et al. 2015 CES — 雙孔隙多尺度萃取模型，實驗驗證（fast surface + slow kernel）
- Moroney et al. 2016 J. Math. Ind. — well-mixed 萃取動力學
- Moroney et al. 2016 SIAM J. Appl. Math. — 主導機制的漸近分析
- Moroney et al. 2019 PLOS ONE — 床層萃取均勻性，數學模型 + CFD（含 drip filter 幾何）
- Cameron et al. 2020 Matter — espresso：PSD、不均勻流、重現性；細研磨反而萃取下降
- Giacomini et al. 2020 IJMF — in-silico espresso 的多孔介質流與傳輸
- Ellero & Navarini 2019 JFE（mesoscopic espresso）、Sano et al. 2019 JFE（volume averaging）
- Liang, Chan & Ristenpart 2021 Sci. Rep. — 全浸泡的平衡脫附模型（TDS/EY）
- Lee, Smith & Arshad 2023 PoF — 雙路徑不均勻萃取
- Matias et al. 2023 PoF — 萃取/滯留連續介質方程
- Schmieder et al. 2023 Foods、Vaca Guerra et al. 2023 JFE（dispersed flow） — 流率/粒徑/溫度對 espresso 動力學
- Estévez-Sánchez et al. 2025 JFE — PSD 對萃取傳質的影響
- Egidi, Giacomini et al. 2024 Chaos Sol. Fract.（EY 數值格式）
- Booth et al. 2013 (study-group report) — drip filter 床形演化與萃取

### B. 咖啡床層水力：滲透率、膨潤、fines、侵蝕 — 13 篇
- Corrochano et al. 2015 JFE — 咖啡床穩態滲透率量測法；Kozeny-Carman 高估
- Corrochano 2017 (thesis) — coffee extraction 工程理解
- Mo et al. 2021/2022/2023 (PoF, PoF, Sci. Rep.) — SPH：侵蝕、膨潤、XCT 微結構→滲透率
- Mo et al. 2023 JFE（1D coarse-grained 膨潤）；Hargarten 2020；Maille 2020（膨潤是否存在有爭議）
- Vaca Guerra et al. 2022 JFE（PSD 對 espresso，packed bed compression）
- Smrke et al. 2024 Sci. Rep. — fines 降滲透率
- Foster et al. 2025 PoF — espresso 浸潤前緣 μCT + 1D 非飽和流
- Wadsworth et al. 2026 RSOS — grind → 比表面積/孔隙 → 滲透率，XCT + LBM 驗證
- Waszkiewicz et al. 2026 PoF — poroelastic 流量調節
- Angeloni, Giacomini et al. 2023 Appl. Sci.（espresso 電腦滲流模型回顧）

### C. 重力驅動手沖 / 濾杯（直接相關）— 10 篇
- **Lee & Chang 2026 npj Sci. Food** — reduced-order 守恆框架；PSD 校準後 held-out 研磨度預測
  drawdown、杯量、TDS
- **Siregar 2026 Eur. J. Phys.** — 錐形 Darcy pour-over 教學模型（無實驗）
- Park et al. 2025 PoF — 注水水柱 avalanche 混合
- Santanatoglia et al. 2023 JFCA — 人為因素的重現性（V60 vs Pure Brew 等）
- Pure Brew comparative study 2023 LWT；Lin et al. 2024 JAFR（濾杯水流方向）
- Study on pour-over flavour 2022 FFJ；Batali et al. 2020 Sci. Rep.（溫度對 drip 感官）
- Caffeine in filter brews vs roast & EY 2024 Sci. Rep.；Smith & Lee 2020 EJP（Brewing optimal coffee）

### D. PSD 量測方法與尺度不確定度 — 10 篇
- Uman et al. 2016 Sci. Rep. — 磨豆 PSD（雷射繞射）、溫度與產地效應
- Khongphinitbunjong et al. 2025 JFPE — 12 研磨刻度 × 3 焙度的 Rosin–Rammler PSD
- Oec 2026 preprint — 影像 PSD 特徵與 TDS 相關
- Méndez Harper & Hendon 2023–24（iScience）— 磨豆靜電
- Digital image analysis of coffee particles (2024 Powder Tech.)
- Angeloni et al. 2023 EFRT — PSD 均勻度對飲品性質
- Image analysis vs laser diffraction (2006 AAPS)；sieving/sedimentation/LD 相容性 (2024 STR)
- Effect of pressure on espresso PSD (2018 KIMIKA)

### E. 土壤/沉積物：由 PSD 預測滲透率（方法論對照）— 7 篇
- Koltermann & Gorelick 1995 WRR — fractional packing model
- Urumović 2016 HESS — Kozeny-Carman 的代表粒徑與有效孔隙率
- Wang, François & Lambert 2017 WRR — PSD 推滲透率的因次分析
- Ren & Santamarina 2018 Eng. Geol. — 孔徑觀點
- Nguyen & Indraratna 2020 Géotech. Lett.（顆粒形狀）、Říha et al. 2018 JHH（玻璃珠經驗式）
- Nakajima & Stadler 2006 HESS（one-step outflow）、Mortensen, Glass et al. 2001 WRR（retention/outflow 可視化）

**意義**：「由 PSD 預測滲透率」在土壤學是成熟問題，經驗式（Hazen、Kozeny-Carman、
Beyer 等）在不同材料上誤差常達一個數量級。咖啡的新意不在 PSD→k 本身，而在
（a）咖啡特有的 fines/膨潤/CO₂，（b）重力驅動、非飽和、間歇注水的暫態，（c）尺度錨的
不確定度。

## 主要研究群
- **Lee, W. T. / Moroney / Foster / Hendon**（Limerick、Portsmouth、Oregon）— 萃取模型主線
- **Ellero / Mo / Navarini**（BCAM、illycaffè）— SPH 粒子方法
- **Ristenpart / Guinard**（UC Davis）— 浸泡/滴濾實驗、感官
- **Yeretzian / Smrke**（ZHAW）— espresso 動力學、fines
- **Lee, H. S. & Chang, B.-Y.**（韓國）— 濾杯守恆約束框架（2026）
- **Mathijssen**（UPenn）— pour-over 流體力學

## 出處分布
以 `paper_db.jsonl` 的 venue 欄為準；Physics of Fluids、J. Food Eng.、Sci. Rep. 為三大出處。
