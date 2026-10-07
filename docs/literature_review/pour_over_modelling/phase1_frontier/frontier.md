# Phase 1 — Frontier (2022–2026)

Date: 2026-10-07 | Source: OpenAlex（Semantic Scholar 無 API key 被限流，改用 OpenAlex）
Raw results: `search_results/oa_*.jsonl`（7 組查詢 × 50 筆）

## 查詢

| tag | query | filter |
|---|---|---|
| pourover | "pour-over coffee" | ≥ 2022 |
| drip | "drip filter coffee brewing" | ≥ 2022 |
| perm | "coffee bed permeability" | ≥ 2022 |
| kin | "coffee extraction kinetics modelling" | ≥ 2022 |
| psd | "coffee grind particle size distribution" | ≥ 2022 |
| esp | "espresso extraction flow model" | ≥ 2022 |
| fines | "coffee fines" | ≥ 2022 |

雜訊極高（spent coffee grounds、化學成分、感官、ESPRESSO 光譜儀等）；與沖煮物理相關者約 25 篇。

## 近期重點論文（與本專案主張的距離由近到遠）

1. **Lee & Chang (2026), npj Science of Food** — *Coffee brewing trajectories from recipe-level
   records: a conservation-constrained framework for filter coffee.* DOI 10.1038/s41538-026-01074-1
   Reduced-order、守恆約束的濾杯框架；以 coarse/medium/fine 三組 measured PSD 的沖煮估計有效
   參數並固定，**對 held-out 的 medium-coarse / medium-fine 預測** drawdown time（MAE 6.7 s）、
   杯量（0.58 g）、TDS（0.020 pp）。**與「measured PSD → 跨研磨度預測 drawdown」主張直接重疊。**
2. **Siregar (2026), European Journal of Physics** — 錐形幾何 Darcy + 守恆 + 現象學萃取的
   pour-over 教學模型；無新實驗，只用文獻值。DOI 10.1088/1361-6404/ae614b
3. **Wadsworth et al. (2026), Royal Society Open Science** — 咖啡粉餅滲透率理論模型
   （連通孔隙率 ϕp 與比表面積 s），以 XCT + lattice-Boltzmann 在 11 個研磨刻度驗證。
   DOI 10.1098/rsos.252031
4. **Oec (2026), engrXiv preprint** — 影像分析 PSD 的 area-weighted peak 與 TDS 的 Spearman
   相關（兩台磨豆機 × 6 刻度，ρ = −0.949）；統計相關，無機制模型。DOI 10.31224/7507
5. **Park, Young & Mathijssen (2025), Physics of Fluids** — pour-over 注水水柱衝擊造成的
   avalanche 混合；矽膠顆粒可視化 + 真實咖啡 TDS。DOI 10.1063/5.0257924
6. **Foster et al. (2025), Physics of Fluids** — espresso 初始浸潤，time-resolved μCT 與 1D
   非飽和流模型比較。DOI 10.1063/5.0245167
7. **Estévez-Sánchez et al. (2025), J. Food Eng.** — PSD 對固液萃取傳質的影響（state-space
   解析解），用文獻資料估計咖啡擴散係數。DOI 10.1016/j.jfoodeng.2025.112511
8. **Waszkiewicz et al. (2026), Physics of Fluids** — espresso 床的 poroelastic 流量調節。
9. **Lee, Smith & Arshad (2023), Physics of Fluids** — 雙路徑低維模型解釋細研磨的不均勻萃取。
10. **Matias et al. (2023), Physics of Fluids** — 多孔介質萃取/滯留的連續介質方程（Pe 數、傳質率）。
11. **Mo et al. (2022, 2023), PoF / Sci. Rep. / JFE** — SPH 模擬膨潤、XCT 微結構與流動。
12. **Smrke et al. (2024), Sci. Rep.** — fines 對 espresso 萃取動力學的角色。
13. **Santanatoglia et al. (2023), JFCA** — 六位咖啡師 × 四種濾沖法的重現性；V60 TDS 與沖煮時間
    重現性佳，注水擾動是主要變因。

## 趨勢

- **Physics of Fluids 成為咖啡流體力學的主要出口**（2021–2026 至少 7 篇），主題集中在
  espresso（浸潤、膨潤、侵蝕、poroelasticity）與低維模型（不均勻萃取、注水混合）。
- **影像式 PSD 量測普及化**：低成本影像 PSD 與 TDS 的相關（Oec 2026）、磨豆靜電（Harper/Hendon
  2024 iScience）、顆粒形狀辨識（Powder Tech 2024）。
- **手沖（gravity-driven）建模在 2025–2026 才開始出現**：Park 2025（混合）、Siregar 2026
  （教學模型）、Lee & Chang 2026（守恆約束 + held-out 研磨度預測）。這個方向正在被填補，
  且速度很快。
- 尚未看到：手沖的**時間解析出液曲線**（V_out(t)）擬合、熱模型耦合、per-PSD-bin 萃取、
  或 identifiability 分析；需在 Phase 3 讀 Lee & Chang 全文確認。
