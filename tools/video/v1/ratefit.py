# 由計時器「跳秒」事件時刻擬合週期 P（影片秒/計時器秒）：網格搜尋 (P, 相位) 使落在 ±tol 內的事件最多，
# 再對 inlier 做最小平方 t = t0 + k·P。rate = 1/P = 計時器秒/影片秒。
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
from common import REPO, WORK, VIDEO_CASES, frame_video_t, log_base, mov_path  # noqa: E402,F401  路徑/時刻慣例見 tools/video/common.py
import sys, numpy as np, json
tol = 0.05
out = {}
for v in ("IMG_3346", "IMG_3347", "IMG_3405"):
    tt = np.load(f"{WORK}/vid/trans_{v}.npy")
    best = (0, None)
    for P in np.arange(0.95, 1.05, 0.0002):
        for ph in np.arange(0, P, 0.01):
            r = (tt - ph) / P; res = (r - np.round(r)) * P
            s = int(np.sum(np.abs(res) < tol))
            if s > best[0]: best = (s, (P, ph))
    P, ph = best[1]
    r = (tt - ph) / P; k = np.round(r); res = (r - k) * P; m = np.abs(res) < tol
    A = np.vstack([np.ones(m.sum()), k[m]]).T
    (t0, P2), *_ = np.linalg.lstsq(A, tt[m], rcond=None)
    rr = tt[m] - (t0 + P2 * k[m]); se = np.sqrt(np.sum(rr**2)/(m.sum()-2) / np.sum((k[m]-k[m].mean())**2))
    out[v] = dict(P=P2, P_se=se, rate=1/P2, t0=t0, n_in=int(m.sum()), n_ev=len(tt), span_s=float(tt[m].max()-tt[m].min()), rms=float(np.sqrt(np.mean(rr**2))))
    print(v, {a: (round(b, 5) if isinstance(b, float) else b) for a, b in out[v].items()})
json.dump(out, open(f"{WORK}/vid/ratefit.json", "w"), indent=1)
