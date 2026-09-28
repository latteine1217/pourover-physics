# 計時器 QC：以 ratefit 的速率 b，求 a 使 floor(a + b·t) 與逐格讀值一致最多；列出不一致格。
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
from common import REPO, WORK, VIDEO_CASES, frame_video_t, log_base, mov_path  # noqa: E402,F401  路徑/時刻慣例見 tools/video/common.py
import json, csv, numpy as np
R = json.load(open(f"{WORK}/vid/ratefit.json"))
def load(v):
    rows = []
    for line in open(f"{WORK}/vid/sc_{v}.txt"):
        p = line.rstrip("\n").split(",", 3)
        rows.append(dict(frame=int(p[0]), timer=int(p[1]) if p[1] else None, w=float(p[2]) if p[2] else None, note=p[3] if len(p) > 3 else ""))
    return rows
vt = frame_video_t   # f_k 實際影片時刻（單一定義見 common.frame_video_t）
out = {}
for v in ("IMG_3346", "IMG_3347", "IMG_3405"):
    b = R[v]["rate"]; rows = load(v)
    obs = [(vt(r["frame"], v), r["timer"], r["frame"]) for r in rows if r["timer"] is not None and "stopped" not in r["note"]]
    best = None
    for a in np.arange(-15, 0, 0.001):
        ok = sum(int(np.floor(a + b*t)) == n for t, n, _ in obs)
        if best is None or ok > best[0]: best = (ok, a)
    # a 的可行區間（全部一致的 a 範圍）
    good = [a for a in np.arange(best[1]-1, best[1]+1, 0.001) if sum(int(np.floor(a + b*t)) == n for t, n, _ in obs) == best[0]]
    a_lo, a_hi = min(good), max(good); a = (a_lo + a_hi)/2
    bad = [(f, n, int(np.floor(a + b*t))) for t, n, f in obs if int(np.floor(a + b*t)) != n]
    t_start = -a / b
    out[v] = dict(b=b, a=a, a_range=[a_lo, a_hi], n_obs=len(obs), n_agree=best[0], mismatches=bad, timer_zero_video_t=t_start)
    print(v, f"b={b:.5f} a={a:.3f} [{a_lo:.3f},{a_hi:.3f}] agree {best[0]}/{len(obs)} timer0 at video t={t_start:.2f}s", "mismatch:", bad)
json.dump(out, open(f"{WORK}/vid/timer_model.json", "w"), indent=1)
