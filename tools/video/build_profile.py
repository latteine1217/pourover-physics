"""
tools/video/build_profile.py — 由錄影逐格判讀組出 1 s 格點的 flow profile（F10，2026-09-27）

用法：
    uv run python tools/video/build_profile.py            # 三支影片全部
    uv run python tools/video/build_profile.py IMG_3346   # 指定影片

輸入（皆在 `data/<case>/video/`，由 V1/V2 腳本產生，見 tools/video/README.md）：
    <VID>_displays.csv     逐格秤重 / 秤計時器 / 雙通道溫度（V1）
    <VID>_level.csv        逐格分享壺液面前緣體積與品質旗標（V2）
    <VID>_timer_model.json 秤計時器模型 timer = a + b·video_t（V1）
    以及同 case 的紀錄表 `<stem>_flow_profile.csv`（只取首列 meta，數值不用）。

輸出：
    data/<case>/<stem>_flow_profile_video.csv
    data/<case>/video/<VID>_profile_build.json   組建摘要（停流時刻、終值、可見起點…）

What（每一欄的定義）：
    time_s               真實秒 t = video_t − timer_zero_video_t（t = 0 = 秤計時器自動觸發
                         = 注水起點；觸發前 ≤ 1.2 g 的注水量併入 t ≥ 0 的第一格，≤ 1 s 取樣量化內）
    scale_timer_s        同一時刻秤計時器的模型讀值 b·t（b = 1.0181–1.0189，逐片）
    poured_weight_g      秤讀值（逐格線性內插到 1 s 格點；running max 去除 ≤ 0.1 g 秤漂移）
    drained_volume_ml    液面前緣體積 V_liquid_front（V2），以 1/σ² 加權等張回歸（PAVA）單調化：
                         壺內液量只增不減，但 running max 會取雜訊上包絡（實測平均偏高
                         0.05–0.54 mL、最多 +2.9 mL）；PAVA 是最小平方意義下的單調投影，無此偏差
    drained_sigma_ml     逐點 1σ：ok 4 mL；estimator_spread / visual_override / visual_interp 6 mL；
                         low_extrap（V < 50 mL 外插）或液面不可見 15 mL
    foam_thickness_ml    前壁泡沫帶厚度（診斷，不進 χ²）
    server_temp_C / outflow_temp_C / temp_flag
                         最近一格 LCD 上行（分享壺）/ 下行（出水口）讀值與鬼影旗標（診斷）
    phase                pour / pause / flow_stop_visual / dripper_off_final
                         flow_stop_visual = `observation.level_stop_time` 的跨越時刻所在列（向上取整）：
                         最後一注結束後，5 點平滑液位首次到達終值 2 mL 內；終值 = 可用液位列最後 6 s
                         的中位數（常數唯一來源 `measured_io.STOP_TOL_ML` 等，模型端共用同一函式）。
                         dripper_off_final = 觀測末列（讀取最終壺溫；濾杯移開時刻另見下）。
    use_for_fit          液面不可見（兩端可見格間隔 > 1.5 s 或在首個可見格之前）= 0；
                         濾杯移開後（`<VID>_annotations.json` 的 dripper_removed_frame 起）= 0，
                         drained_quality 加 `after_dripper_removed`（F12a）
    dripper_removed_time_s（meta）
                         濾杯開始移離壺口的影格時刻（真實秒）；無 annotations 檔則留空
Why:
    紀錄表 drained 欄經同一影片證實悶蒸後系統性偏高 13–73 mL（V2），不能當 Class A；
    影片前緣讀值 V ≥ 50 mL 時 ±3–4 mL。秤計時器比真實時鐘快 1.86%（V1），因此影片版時間軸
    直接用真實秒，不再經秤計時器。
"""

import csv
import json
import sys
from pathlib import Path

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parent)]
from common import VIDEO_CASES, case_dir, frame_video_t, log_base  # noqa: E402
sys.path[:0] = [str(Path(__file__).resolve().parents[2])]
from pour_over.measured_io import FINAL_WINDOW_S, STOP_TOL_ML, meta_consensus  # noqa: E402
from pour_over.observation import level_stop_time  # noqa: E402

SIGMA_OK_ML = 4.0          # V2 §6：V ≥ 50 mL 隨機誤差 ±3 mL、目視 vs 自動 SD 1.5–4.7
SIGMA_VISUAL_ML = 6.0      # 目視判讀 / 估計器分歧 > 6 px（≈ 4–6 mL）
SIGMA_LOW_ML = 15.0        # V < 50 mL 外插 / 液面不可見（V2 §1）
POUR_RATE_THR_G_S = 0.3    # 與 V1 注水段判定同一門檻
MAX_VISIBLE_GAP_S = 1.5
META_KEYS_REQUIRED = ("dose_g", "roast", "grinder", "grinder_setting", "bed_height_cm", "brew_temp_C")


def _f(x: str) -> float:
    return float(x) if x not in ("", None) else float("nan")


def _sigma_of(quality: str) -> float:
    if "low_extrap" in quality:
        return SIGMA_LOW_ML
    if any(tag in quality for tag in ("visual_override", "visual_interp", "estimator_spread", "median3")):
        return SIGMA_VISUAL_ML
    return SIGMA_OK_ML


def _isotonic(y: np.ndarray, w: np.ndarray) -> np.ndarray:
    """加權等張回歸（pool-adjacent-violators），回傳與 y 等長的非遞減序列。"""
    blocks: list[list[float]] = []            # [均值, 權重, 個數]
    for yi, wi in zip(y, w):
        blocks.append([float(yi), float(wi), 1])
        while len(blocks) > 1 and blocks[-2][0] > blocks[-1][0]:
            a, b_ = blocks.pop(), blocks.pop()
            wt = a[1] + b_[1]
            blocks.append([(a[0] * a[1] + b_[0] * b_[1]) / wt, wt, a[2] + b_[2]])
    return np.concatenate([np.full(n, m) for m, _, n in blocks])


def _running_max(x: np.ndarray) -> tuple[np.ndarray, int]:
    m = np.maximum.accumulate(x)
    return m, int(np.sum(m > x + 1e-12))


def build(vid: str) -> dict:
    cdir = case_dir(vid)
    vdir = cdir / "video"
    stem = VIDEO_CASES[vid][1]
    ann_path = vdir / f"{vid}_annotations.json"
    ann = json.loads(ann_path.read_text()) if ann_path.exists() else {}
    tm = json.loads((vdir / f"{vid}_timer_model.json").read_text())["timer_model"]
    b, t0 = float(tm["b"]), float(tm["timer_zero_video_t"])

    disp = list(csv.DictReader(open(vdir / f"{vid}_displays.csv", encoding="utf-8")))
    lev = {int(r["frame"]): r for r in csv.DictReader(open(vdir / f"{vid}_level.csv", encoding="utf-8"))}
    log_rows = list(csv.DictReader(open(f"{log_base(vid)}_flow_profile.csv", encoding="utf-8")))
    # 逐列 meta 取共識值（例：首列 dripper_mass_g 224.1 vs 其餘列 123.5），規則同主流程。
    log_meta, meta_fixes = meta_consensus(log_rows)
    for fx in meta_fixes:
        print(f"{vid}: {fx['field']} {fx['old']:g} -> {fx['new']:g} ({fx['rule']})")
    meta_keys = list(log_meta.keys())[: list(log_meta.keys()).index("time_mmss")]
    for k in META_KEYS_REQUIRED:
        if k not in meta_keys:
            raise ValueError(f"{vid}: 紀錄表 meta 缺 {k}")

    frame = np.array([int(r["frame"]) for r in disp])
    t_f = np.array([float(r["video_t_s"]) for r in disp]) - t0        # 真實秒
    w_f = np.array([_f(r["poured_g"]) for r in disp])
    ts_f = np.array([_f(r["T_upper_server_C"]) for r in disp])
    to_f = np.array([_f(r["T_lower_outflow_C"]) for r in disp])
    flag_f = [r["lcd_flag"] for r in disp]

    # ── 液位（以 V1 的逐格影片時刻對齊；V2 的 video_t = k − 1 慣例不用）────────
    v_f = np.array([_f(lev[k]["V_liquid_front_ml"]) if k in lev else np.nan for k in frame])
    q_f = [lev[k]["quality"] if k in lev else "missing" for k in frame]
    foam_f = np.array([_f(lev[k]["foam_thickness_ml"]) if k in lev else np.nan for k in frame])
    ok = np.isfinite(v_f)
    t_lv = t_f[ok]
    s_lv = np.array([_sigma_of(q) for q, o in zip(q_f, ok) if o])
    v_lv = _isotonic(v_f[ok], 1.0 / s_lv ** 2)
    n_v_iso = int(np.sum(np.abs(v_lv - v_f[ok]) > 0.05))
    qual_lv = [q for q, o in zip(q_f, ok) if o]

    t_end = float(np.floor(t_lv.max()))
    grid = np.arange(0.0, t_end + 1e-9, 1.0)
    # 濾杯移開（F12a）：移開影格的前一格是最後一個「濾杯在壺上」的液位讀值；
    # 格點時刻晚於它的列需要移開後的影格內插 → 不可與模型 V_cup 比較。
    t_removed = None
    t_last_on = float("inf")
    if "dripper_removed_frame" in ann:
        k_rm = int(ann["dripper_removed_frame"])
        t_removed = frame_video_t(k_rm, vid) - t0
        t_last_on = frame_video_t(k_rm - 1, vid) - t0

    # ── 注水：t = 0 定為 0 g（見 docstring），其後逐格內插 ────────────────────
    okw = np.isfinite(w_f)
    pour_t = np.concatenate([[0.0], t_f[okw & (t_f > 0.0)]])
    pour_w = np.concatenate([[0.0], w_f[okw & (t_f > 0.0)]])
    poured = np.interp(grid, pour_t, pour_w)
    poured, n_w_mono = _running_max(np.round(poured, 1))

    # ── 出液：可見段內插；首個可見格前以 (0, 0) 空壺錨點內插並標為不可見 ───────
    anchor_t = np.concatenate([[0.0], t_lv])
    anchor_v = np.concatenate([[0.0], v_lv])
    drained = np.interp(grid, anchor_t, anchor_v)
    drained = np.maximum.accumulate(np.round(drained, 1))   # 只消除 0.1 mL 捨入回落
    idx_hi = np.searchsorted(t_lv, grid, side="left")
    visible = np.zeros(grid.size, dtype=bool)
    sigma = np.full(grid.size, SIGMA_LOW_ML)
    qual = ["not_visible_interp"] * grid.size
    for i, (tg, j) in enumerate(zip(grid, idx_hi)):
        if j < t_lv.size and abs(t_lv[j] - tg) < 1e-9:
            lo = hi = j
        elif 0 < j < t_lv.size:
            lo, hi = j - 1, j
        else:
            continue
        if t_lv[hi] - t_lv[lo] <= MAX_VISIBLE_GAP_S:
            visible[i] = True
            sigma[i] = max(s_lv[lo], s_lv[hi])
            qual[i] = qual_lv[hi] if (t_lv[hi] - tg) <= (tg - t_lv[lo]) else qual_lv[lo]
    foam = np.interp(grid, t_f[np.isfinite(foam_f)], foam_f[np.isfinite(foam_f)],
                     left=np.nan, right=np.nan) if np.isfinite(foam_f).any() else np.full(grid.size, np.nan)

    # ── 溫度：最近一格（≤ 0.6 s）讀值 + 旗標，不內插 ─────────────────────────
    near = np.array([int(np.argmin(np.abs(t_f - tg))) for tg in grid])
    near_ok = np.abs(t_f[near] - grid) <= 0.6
    t_srv = np.where(near_ok, ts_f[near], np.nan)
    t_out = np.where(near_ok, to_f[near], np.nan)
    t_flag = [flag_f[j] if o else "no_frame" for j, o in zip(near, near_ok)]

    # ── 相位與停流 ──────────────────────────────────────────────────────────
    w_rate = np.gradient(np.interp(grid, pour_t, pour_w), grid)
    pouring = w_rate > POUR_RATE_THR_G_S
    last_pour_end = float(grid[np.flatnonzero(pouring)[-1]])
    on_server = grid <= t_last_on + 1e-9
    usable = visible & on_server
    t_end_obs = float(grid[usable].max())
    v_final = float(np.median(drained[usable & (grid >= t_end_obs - FINAL_WINDOW_S)]))
    t_stop = level_stop_time(grid, drained, usable, last_pour_end)
    if t_stop >= t_end_obs:
        raise ValueError(f"{vid}: 最後一注後液位未到達終值 {v_final:.1f} ± {STOP_TOL_ML} mL")
    i_stop = int(np.ceil(t_stop - 1e-9))
    if i_stop >= grid.size - 1:
        raise ValueError(f"{vid}: 停流時刻落在觀測末列，無法與 dripper_off_final 分開")
    phase = np.where(pouring, "pour", "pause").astype(object)
    phase[i_stop] = "flow_stop_visual"
    phase[-1] = "dripper_off_final"

    # ── 最終壺溫（紀錄表 meta 空白時）：末 3 個上行無旗標格的中位數 ────────────
    meta = {k: log_meta[k] for k in meta_keys}
    if str(meta.get("final_coffee_temp_C", "")).strip():
        temp_src = "log_meta"
    else:
        upper_ok = [not any(seg.strip().startswith("U") for seg in f.split(";")) for f in flag_f]
        cand_f = [j for j in range(len(disp))
                  if np.isfinite(ts_f[j]) and upper_ok[j] and t_f[j] <= t_end + 0.6]
        pick = cand_f[-3:]
        meta["final_coffee_temp_C"] = f"{float(np.median(ts_f[pick])):.1f}"
        temp_src = (f"video:{vid} server_temp_C median of frames "
                    f"{','.join(str(frame[j]) for j in pick)} (t={t_f[pick[0]]:.1f}-{t_f[pick[-1]]:.1f} s)")
    meta.update({"time_base": "real_s", "source": f"video:{vid}",
                 "final_coffee_temp_source": temp_src, "scale_timer_rate_b": f"{b:.5f}",
                 "dripper_removed_time_s": "" if t_removed is None else f"{t_removed:.2f}"})

    rows = []
    for i, tg in enumerate(grid):
        notes = []
        if not visible[i]:
            notes.append("level not visible; interpolated (not in fit)")
        elif not on_server[i]:
            notes.append("after dripper removed from server (not comparable with model; not in fit)")
        elif "low_extrap" in qual[i]:
            notes.append("V<50 mL extrapolated below lowest tick")
        if phase[i] == "flow_stop_visual":
            notes.append(f"smoothed level within {STOP_TOL_ML:g} mL of final {v_final:.1f} mL "
                         f"(sub-grid crossing t = {t_stop:.2f} s)")
        if phase[i] == "dripper_off_final":
            notes.append("end of video observation (final server temperature read)")
        q_row = qual[i] if on_server[i] or not visible[i] else f"{qual[i]};after_dripper_removed"
        rows.append({
            **meta,
            "time_mmss": f"{int(tg) // 60:02d}:{int(tg) % 60:02d}",
            "time_s": f"{tg:.0f}",
            "scale_timer_s": f"{b * tg:.3f}",
            "poured_weight_g": f"{poured[i]:.1f}",
            "drained_volume_ml": f"{drained[i]:.1f}",
            "drained_sigma_ml": f"{sigma[i]:.1f}",
            "drained_quality": q_row,
            "foam_thickness_ml": "" if not np.isfinite(foam[i]) else f"{foam[i]:.1f}",
            "server_temp_C": "" if not np.isfinite(t_srv[i]) else f"{t_srv[i]:.1f}",
            "outflow_temp_C": "" if not np.isfinite(t_out[i]) else f"{t_out[i]:.1f}",
            "temp_flag": t_flag[i],
            "phase": phase[i],
            "use_for_fit": "1" if usable[i] else "0",
            "notes": "; ".join(notes),
        })
    out_csv = cdir / f"{stem}_flow_profile_video.csv"
    with out_csv.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    summary = {
        "video_id": vid, "output": str(out_csv.relative_to(case_dir(vid).parents[2])),
        "timer_b": b, "timer_zero_video_t": t0, "t_end_s": t_end, "n_rows": int(grid.size),
        "first_visible_level_t_s": float(t_lv.min()), "n_use_for_fit": int(usable.sum()),
        "last_pour_end_s": last_pour_end, "flow_stop_visual_s": float(grid[i_stop]),
        "flow_stop_level_subgrid_s": float(t_stop), "t_end_level_obs_s": t_end_obs,
        "dripper_removed_frame": ann.get("dripper_removed_frame"),
        "dripper_removed_time_s": t_removed,
        "n_level_rows_after_dripper_removed": int(np.sum(visible & ~on_server)),
        "n_median3_frames": int(sum("median3" in q for q in q_f)),
        "v_final_ml": v_final, "poured_final_g": float(poured[-1]),
        "retained_final_g": float(poured[-1] - drained[-1]),
        "final_coffee_temp_C": float(meta["final_coffee_temp_C"]), "final_coffee_temp_source": temp_src,
        "poured_running_max_rows": n_w_mono, "drained_isotonic_adjusted_frames": n_v_iso,
    }
    (vdir / f"{vid}_profile_build.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False))
    return summary


if __name__ == "__main__":
    for v in (sys.argv[1:] or list(VIDEO_CASES)):
        print(json.dumps(build(v), ensure_ascii=False))
