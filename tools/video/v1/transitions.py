# 以全幀率(30 fps)讀取秤計時器「秒個位數」區域，偵測其變化時刻，
# 擬合 transition_time = t0 + k / rate，得到計時器相對影片時鐘的速率比。
# What: 客觀量測時鐘速率比。Why: fps=1 抽樣相位接近計時器跳秒時刻，目視 skip 可能是取樣假象。
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
from common import REPO, WORK, VIDEO_CASES, frame_video_t, log_base, mov_path  # noqa: E402,F401  路徑/時刻慣例見 tools/video/common.py
import sys, subprocess, numpy as np
v, box = sys.argv[1], [int(x) for x in sys.argv[2].split(",")]   # 秒個位數框 x,y,w,h
w, h = box[2], box[3]
cmd = ["ffmpeg", "-loglevel", "error", "-i", str(mov_path(v)),
       "-vf", f"crop={w}:{h}:{box[0]}:{box[1]},format=gray", "-f", "rawvideo", "-"]
raw = subprocess.run(cmd, capture_output=True).stdout
F = np.frombuffer(raw, np.uint8).reshape(-1, h, w).astype(float)
n = len(F); t = np.arange(n) / VIDEO_CASES[v][2]
d = np.abs(np.diff(F, axis=0)).mean(axis=(1, 2)); np.save(f"{WORK}/vid/d_{v}.npy", d)
thr = np.median(d) + 8 * np.median(np.abs(d - np.median(d)))
idx = np.where(d > thr)[0]
# 合併相鄰幀（一次跳秒可能跨 1–3 幀的淡入淡出）
ev = []
for i in idx:
    if ev and i - ev[-1][-1] <= 5: ev[-1].append(i)
    else: ev.append([i])
tt = np.array([t[e[int(np.argmax(d[e]))]] + 0.5/30 for e in ev])
np.save(f"{WORK}/vid/trans_{v}.npy", tt)
print(v, "frames", n, "events", len(tt))
print(np.round(tt, 3).tolist())
