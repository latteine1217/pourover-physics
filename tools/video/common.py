"""
tools/video/common.py — 錄影量測腳本共用的路徑與時刻慣例（F10，2026-09-27）

What:
    - `REPO`：專案根目錄（環境變數 `POUR_OVER_REPO` 可覆寫，預設為本檔上兩層）。
    - `WORK`：抽格與中間檔的工作目錄（環境變數 `VIDEO_WORK`，預設為目前目錄）。
      慣例：`WORK/vid/<VID>/f_%04d.jpg`（ffmpeg fps=1 抽格）、`WORK/vid/sc_<VID>.txt`
      / `th_<VID>.txt`（目視判讀）、`WORK/v2/raw_<VID>.json`（液位偵測原始輸出）。
    - `VIDEO_CASES`：影片 ↔ 量測 case 的對應（case 目錄、紀錄表 stem、幀率）。
    - `frame_video_t(k, vid)`：fps=1 抽格 `f_k` 的實際影片時刻。
Why:
    V1/V2 原型把 scratchpad 與 repo 的絕對路徑寫死在各腳本裡；集中到一處後，
    重跑只需設定兩個環境變數，且 f_k 時刻慣例只有一份定義（V1 逐幀比對驗證）。
"""

import os
from pathlib import Path

import numpy as np

REPO = Path(os.environ.get("POUR_OVER_REPO", Path(__file__).resolve().parents[2]))
WORK = Path(os.environ.get("VIDEO_WORK", "."))

# VID → (case 目錄（相對 REPO）, 紀錄表 stem, 幀率)
VIDEO_CASES: dict[str, tuple[str, str, float]] = {
    "IMG_3346": ("data/kinu_29_light/4:12", "kinu29_light_20g", 30.0),
    "IMG_3347": ("data/kinu_27_light/4:12", "kinu27_light_20g", 30.0),
    "IMG_3405": ("data/kinu_28_light/4:20", "kinu28_light_20g", 30000 / 1001),
}


def case_dir(vid: str) -> Path:
    """影片所屬 case 的目錄（絕對路徑）。"""
    return REPO / VIDEO_CASES[vid][0]


def log_base(vid: str) -> Path:
    """紀錄表路徑的共同前綴（`<base>_flow_profile.csv`、`<base>_thermal_profile.csv`）。"""
    return case_dir(vid) / VIDEO_CASES[vid][1]


def mov_path(vid: str) -> Path:
    """原始錄影（不進版控，見 .gitignore）。"""
    return case_dir(vid) / f"{vid}.MOV"


def frame_video_t(k: int, vid: str) -> float:
    """
    fps=1 抽格 `f_k` 的實際影片時刻 [s]。

    What: 30 fps 片 f_k = 第 30(k−1)+14 幀 → t = k − 0.533 s；IMG_3405（29.97 fps）
          實測 f12 → 11.478 s、f130 → 129.529 s，其間線性內插；f_1 = 第 0 幀。
    Why:  V1 以抽格與原始幀逐像素比對驗證；舊假設「f_k ≈ k − 1 s」會讓計時器模型
          在 IMG_3405 出現 4 格不一致（換成實測時刻後 120/120 一致）。
    """
    if k == 1:
        return 0.0
    if vid == "IMG_3405":
        return 11.478 + (k - 12) * (129.529 - 11.478) / 118
    return k - 0.533


# 估計量合併（F12a，2026-09-27）：刻度欄被熱電偶線遮擋時改取三估計量中位數。
# What: `v2/level.wire_px_near_front` ≥ WIRE_OCCLUSION_MIN_PX → 旗標 `tick_col_wire`，液位取
#       median(刻度欄, 無刻度條帶+橢圓修正, 前弧擬合)，旗標 `median3`。
# Why:  刻度欄是唯一不需橢圓修正的估計，未遮擋時它最直接；被線遮擋時它是三者中唯一
#       被系統性抬高的一個（IMG_3347 f107–f130 高 2–5 mL，另兩者彼此一致、且與 R12 的
#       模型殘差結構對應），中位數對單一估計量的偏差穩健，而且不需要知道偏差量。
#       門檻 20 px ≈ 一條 4 px 寬的線在窗內出現 5 列；三支影片全格掃描，非 setup 格的
#       命中恰為 IMG_3347 f107–f130（f106 = 7 px、f131 = 6 px 為線剛進 / 出條帶邊緣）。
WIRE_OCCLUSION_MIN_PX = 20


def merge_level_estimators(y_tick: float, y_strip: float, y_arc: float, y_tick_nbr_median: float,
                           wire_px: int) -> tuple[float, list[str]]:
    """
    三個液位前緣估計量（y, px；刻度欄 / 無刻度條帶+橢圓修正 / 前弧擬合）→ 採用值與品質旗標。

    規則（依序）：
      1. 刻度欄被熱電偶線遮擋（wire_px ≥ WIRE_OCCLUSION_MIN_PX）且三者皆有限 → 中位數，
         旗標 `tick_col_wire;median3`；
      2. 刻度欄與前後 ±2 格中位數差 ≤ 6 px（或鄰格不足）→ 刻度欄（主估計）；
      3. 否則取另兩者平均，旗標 `tick_col_outlier`；
      4. 遮擋但估計量不足以取中位數 → 仍依 2/3，另加 `tick_col_wire`。
    Why: 見 WIRE_OCCLUSION_MIN_PX；規則 2/3 是 V2 的原規則（不變）。
    """
    alt = [v for v in (y_strip, y_arc) if np.isfinite(v)]
    wire = int(wire_px) >= WIRE_OCCLUSION_MIN_PX
    if wire and np.isfinite(y_tick) and len(alt) == 2:
        return float(np.median([y_tick, *alt])), ["tick_col_wire", "median3"]
    q: list[str] = []
    if np.isfinite(y_tick) and (not np.isfinite(y_tick_nbr_median) or abs(y_tick - y_tick_nbr_median) <= 6):
        y = float(y_tick)
    elif alt:
        y = float(np.mean(alt))
        q.append("tick_col_outlier")
    else:
        y = float("nan")
    if wire:
        q.append("tick_col_wire")
    return y, q
