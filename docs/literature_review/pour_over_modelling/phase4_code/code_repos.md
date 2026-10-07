# Phase 4 — Code & Tools

Date: 2026-10-07 | 來源：GitHub REST search（stars 排序）+ 論文 Data/Code Availability。
star 數與最後 push 日期為查詢當日 GitHub API 回傳值。

## 沖煮模型

| Repo | Stars | Lang | Last push | License | 內容 | 與本專案關係 |
|---|---|---|---|---|---|---|
| [Byoung-Yong/FilterCoffee](https://github.com/Byoung-Yong/FilterCoffee) | 1 | Python | 2026-06-04 | MIT | Lee & Chang 2026 npj Sci. Food 的 finite-volume 濾杯模型、15 次沖煮終點量測、5 組 PSD、53 筆公開食譜 | **最接近的競品**；其 15 次沖煮資料可作為本模型的外部測試集（僅終點） |
| [g42alaxy/FilterCoffeePhysics](https://github.com/g42alaxy/FilterCoffeePhysics) | 1 | Python | 2024-11-05 | – | 濾沖沖煮分析平台 | 業餘專案，未讀程式碼 |
| [abdghifary/brewmulator](https://github.com/abdghifary/brewmulator) | 0 | TypeScript | 2026-04-12 | MIT | 「physics-based」萃取模擬器 | 業餘專案，無實驗驗證描述 |
| [alextomp/coffee-extraction-modelling](https://github.com/alextomp/coffee-extraction-modelling) | 0 | Python | 2026-09-19 | – | 真空輔助萃取的動態傳質模型 | 不同沖煮法 |
| [Finne822/Analysis-of-Coffee-Puck](https://github.com/Finne822/Analysis-of-Coffee-Puck) | 0 | – | 2025-02-17 | – | 粉餅影像 → 孔隙率、比表面積、迂曲度，網路模型 | espresso，影像孔隙結構 |
| [latteine1217/pourover-physics](https://github.com/latteine1217/pourover-physics) | 0 | Python | 2026-10-06 | MIT | 本專案 | — |
| [latteine1217/pour-over-coffee-lbm](https://github.com/latteine1217/pour-over-coffee-lbm) | 2 | Python | 2025-09-05 | – | 使用者先前的 3D D3Q19 LBM V60 模擬 | 使用者自己的前作 |

## PSD 量測工具

| Repo | Stars | Lang | Last push | License | 內容 |
|---|---|---|---|---|---|
| [jgagneastro/coffeegrindsize](https://github.com/jgagneastro/coffeegrindsize) | 553 | Python | 2022-12-04 | MIT | 白底照片偵測咖啡顆粒、輸出 PSD；本專案 PSD 的上游 |
| [latteine1217/coffeegrindsize](https://github.com/latteine1217/coffeegrindsize) | 0 | Python | 2026-03-26 | MIT | 使用者 fork，本專案 PSD 匯出欄位契約的來源 |
| [jantielens/coffee-grind-size-analyzer](https://github.com/jantielens/coffee-grind-size-analyzer) | 2 | Python | 2026-02-16 | MIT | 手機照片 + 古典 CV；自述對已知刻度 Pearson r = 0.99 |
| [mgsecure/grind-size](https://github.com/mgsecure/grind-size) | 1 | HTML | 2026-04-30 | MIT | 白底模板照片的網頁版 PSD 分析 |

## 論文附帶資源（未在 GitHub 搜尋命中）

- Oec 2026（engrXiv）：Fiji/ImageJ + Python 影像 PSD 流程，細節見 `phase3_deep_dive/notes_A.md`
- Lee & Chang 2026 web app：https://coffee.echemai.com

## 觀察

- **沒有任何公開 repo 提供手沖的時間解析出液資料集**（V_out(t)、溫度時序）。Lee & Chang 的資料只有
  終點值。本專案 `data/` 下的影片逐格讀值若公開，會是這個領域第一個這類資料集。
- 學術群組（Moroney/Lee、Ellero/Mo、Ristenpart）的模型大多沒有公開程式碼（在 Phase 3 筆記中逐篇確認）。
- coffeegrindsize 是社群事實標準（553 stars），但它的絕對尺度靠使用者給的 px/mm 參考物，
  這正是本專案 PSD 尺度 ±45% 不確定度的來源。
