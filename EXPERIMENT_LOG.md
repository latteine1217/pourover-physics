# 實驗紀錄（已遷移）

本檔自 **2026-09-24** 起不再保存實驗內容，只作為單一入口指標。

**唯一實驗紀錄（single source of truth）：`docs/experiment_log.md`**

---

## 為何遷移

2026-09-24 的全面審核（`docs/audit_2026-09-24.md` §7）指出：
本檔與 `docs/experiment_log.md` 長期並存且內容互異，同一筆實驗在兩處出現不同數字，
讀者無從判斷何者為準。依 AGENTS.md §2.4（維持單一主模型，不保留平行舊分支）與
§8（實驗紀錄規範），紀錄本身也適用同一原則：**只保留一份**。

保留下來的是結構化的 `docs/experiment_log.md`（含 `[SCHEMA]` / `[INDEX]` /
`[BASELINE]` / `[ENTRY]` / `[POLICY]` 區塊），因為它可被 agent 按區塊檢索，
且 active / archived 的分界是顯式的。本檔原有的敘事版內容已完整包含於該檔各 `[ENTRY]`，
未另行備份（git 歷史保有舊版）。

---

## 導覽

| 我要找 | 去 `docs/experiment_log.md` 的 |
|---|---|
| 每筆 entry 的固定欄位定義 | `[SCHEMA]` |
| 目前仍支撐主敘事的實驗 | `[INDEX] Active` |
| 歷史探索（保留證據、非主敘事） | `[INDEX] Archived` |
| 目前的 calibrated 基準與指標 | `[BASELINE] Current` |
| 單筆實驗的改動 / 結果 / 判讀 / artifact | `[ENTRY] <entry_id>` |
| 目前生效的工作規則（loss、gates、凍結參數…） | `[POLICY] Current Working Rules` |

審核總報告：`docs/audit_2026-09-24.md`
文獻對照：`docs/literature_map.md`

---

## 寫入規則

新的實驗、掃描、fitting、benchmark、identifiability 分析一律寫入
`docs/experiment_log.md` 的新 `[ENTRY]`，**不要寫回本檔**。
時間優先取 artifact 檔案修改時間（`ls -l --time-style=full-iso <artifact>`）。
