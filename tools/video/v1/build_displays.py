# V1 產出：逐格顯示值 CSV、注水段表、與紀錄表比對 md。
# What: 將目視判讀（sc_/th_*.txt）+ 計時器模型（timer_model.json）整合成可稽核資料。
# Why: 紀錄表 time_s 為秤計時器；需以影片逐秒讀值檢驗其 poured / 溫度是否抄錄錯位。
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
from common import REPO, WORK, VIDEO_CASES, frame_video_t, log_base, mov_path  # noqa: E402,F401  路徑/時刻慣例見 tools/video/common.py
import csv, json, math
import numpy as np
ROOT = str(REPO / "data")
CASE = {"IMG_3346": ("kinu29 4:12", f"{ROOT}/kinu_29_light/4:12/kinu29_light_20g"),
        "IMG_3347": ("kinu27 4:12", f"{ROOT}/kinu_27_light/4:12/kinu27_light_20g"),
        "IMG_3405": ("kinu28 4:20", f"{ROOT}/kinu_28_light/4:20/kinu28_light_20g")}
TM = json.load(open(f"{WORK}/vid/timer_model.json"))
NOTES = json.load(open(Path(__file__).resolve().parent / "notes.json"))
POUR_THR = 0.3   # g/s：逐秒增量超過此值視為注水中（任務規格）

vt = frame_video_t   # f_k 實際影片時刻（單一定義見 common.frame_video_t）

def load(v):
    sc = {int(p[0]): p for p in (l.rstrip("\n").split(",", 3) for l in open(f"{WORK}/vid/sc_{v}.txt"))}
    th = {int(p[0]): p for p in (l.rstrip("\n").split(",", 3) for l in open(f"{WORK}/vid/th_{v}.txt"))}
    rows = []
    a, b = TM[v]["a"], TM[v]["b"]
    for k in sorted(sc):
        s, t = sc[k], th[k]
        t_v = vt(k, v)
        timer = int(s[1]) if s[1] else None
        stopped = len(s) > 3 and "stopped" in s[3]
        model = a + b*t_v
        rows.append(dict(frame=k, video_t_s=round(t_v, 3), scale_timer_s=timer,
                         timer_model_s=round(model, 2) if timer is not None or s[2] else None,
                         timer_running=(timer is not None and not stopped),
                         poured_g=float(s[2]) if s[2] else None,
                         T_upper_server_C=float(t[1]) if t[1] else None,
                         T_lower_outflow_C=float(t[2]) if t[2] else None,
                         scale_flag=(s[3] if len(s) > 3 else ""), lcd_flag=(t[3] if len(t) > 3 else "")))
    # 計時器未啟動（--:--）前 timer_model 無意義
    for r in rows:
        if r["timer_model_s"] is not None and r["timer_model_s"] < -0.5: r["timer_model_s"] = None
    # 注水判定：與前一個有效讀值之增量 / 影片時間差
    prev = None
    for r in rows:
        r["dW_dt_gps"] = None; r["pouring"] = ""
        if r["poured_g"] is None: continue
        if prev is not None and r["timer_running"]:
            rate = (r["poured_g"] - prev["poured_g"]) / (r["video_t_s"] - prev["video_t_s"])
            r["dW_dt_gps"] = round(rate, 2); r["pouring"] = int(rate > POUR_THR)
        prev = r
    return rows

def pours(rows, v):
    b = TM[v]["b"]; out = []; cur = None
    valid = [r for r in rows if r["poured_g"] is not None]
    for i, r in enumerate(valid):
        if r["pouring"] == 1:
            if cur is None: cur = dict(prev=valid[i-1], rows=[])
            cur["rows"].append(r)
        elif cur is not None:
            cur["end"] = r; out.append(cur); cur = None
    if cur is not None: cur["end"] = cur["rows"][-1]; out.append(cur)
    res = []
    for n, p in enumerate(out, 1):
        p0, last = p["prev"], p["rows"][-1]
        W0, W1 = p0["poured_g"], last["poured_g"]
        dur_v = last["video_t_s"] - p0["video_t_s"]
        rates = [r["dW_dt_gps"] for r in p["rows"]]
        res.append(dict(pour=n, start_after_timer_s=p0["scale_timer_s"], start_by_timer_s=p["rows"][0]["scale_timer_s"],
                        end_timer_s=last["scale_timer_s"], W_before_g=W0, W_after_g=W1, amount_g=round(W1-W0, 1),
                        duration_video_s=round(dur_v, 2), mean_rate_gps_video=round((W1-W0)/dur_v, 2),
                        mean_rate_g_per_timer_s=round((W1-W0)/(dur_v*b), 2), max_1s_rate_gps=max(rates),
                        n_frames=len(p["rows"])))
    return res

def interp_video(rows, key, T):
    # 以計時器模型時間（連續）內插影片讀值
    pts = [(r["timer_model_s"], r[key]) for r in rows if r["timer_model_s"] is not None and r[key] is not None and r["timer_running"]]
    x = np.array([p[0] for p in pts]); y = np.array([p[1] for p in pts])
    if T < x.min() - 0.6 or T > x.max() + 0.6: return None
    return float(np.interp(T, x, y))

def first_reach(rows, W):
    # 影片中重量首次到達 W 的計時器時刻（內插）
    pts = [(r["timer_model_s"], r["poured_g"]) for r in rows if r["timer_model_s"] is not None and r["poured_g"] is not None and r["timer_running"]]
    for (t0, w0), (t1, w1) in zip(pts, pts[1:]):
        if w0 < W - 0.15 and w1 >= W - 0.15:
            return t0 + (t1 - t0) * (W - w0) / (w1 - w0) if w1 != w0 else t1
    return None

def value_at_timer(rows, key, T):
    # 讀值中計時器顯示 == T 的格；若該秒被 fps=1 抽樣跳過則回傳 None
    c = [r[key] for r in rows if r["scale_timer_s"] == T and r["timer_running"] and r[key] is not None]
    return c[0] if c else None

for v, (name, base) in CASE.items():
    rows = load(v)
    cols = ["frame","video_t_s","scale_timer_s","timer_model_s","timer_running","poured_g","dW_dt_gps","pouring",
            "T_upper_server_C","T_lower_outflow_C","scale_flag","lcd_flag"]
    with open(f"{WORK}/vid/{v}_displays.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader()
        for r in rows: w.writerow({k: ("" if r[k] is None else r[k]) for k in cols})
    P = pours(rows, v)
    json.dump(P, open(f"{WORK}/vid/{v}_pours.json", "w"), indent=1)
    # === 與紀錄表比對 ===
    flow = list(csv.DictReader(open(base + "_flow_profile.csv")))
    therm = list(csv.DictReader(open(base + "_thermal_profile.csv")))
    L = [f"# {v} vs record sheet ({name})\n",
         f"- 紀錄表：`{base.replace(ROOT, 'data')}_flow_profile.csv` / `_thermal_profile.csv`",
         f"- 時間軸：秤計時器（`time_s`）。影片值取「計時器顯示 == time_s」之格；該秒被抽樣跳過時以計時器模型 `timer = {TM[v]['a']:.3f} + {TM[v]['b']:.5f}·t_video` 內插（標 *）。",
         f"- `lag_s` = 影片中重量首次到達紀錄值的計時器時刻 − 紀錄 `time_s`（>0 表示紀錄值在影片中較晚才出現 → 紀錄時刻偏早）；僅對注水中（非平台）列有意義。\n",
         "## Poured weight\n",
         "| time_s | phase | sheet poured_g | video poured_g | diff (sheet−video) | lag_s | 判定 |", "|---|---|---|---|---|---|---|"]
    bad = []
    for r in flow:
        T = int(r["time_s"]); Ws = float(r["poured_weight_g"])
        Wv = value_at_timer(rows, "poured_g", T); star = ""
        if Wv is None:
            Wv = interp_video(rows, "poured_g", T); star = "*"
        if T == 0 and Wv is None: Wv, star = 0.0, "(pre-start)"
        lag = first_reach(rows, Ws) if Ws > 0.5 else None
        lag_s = None if lag is None else round(lag - T, 1)
        d = None if Wv is None else round(Ws - Wv, 1)
        verdict = "OK"
        if T == 0:
            verdict = f"計時器由注水觸發：顯示 00:00 時已注 {Wv:.1f} g（非錯誤）" if Wv else "OK"
        elif d is not None and abs(d) > 1.0:
            if lag_s is not None and abs(lag_s) <= 1.5: verdict = f"注水中取樣時刻差（{lag_s:+.1f} s，≤1.5 s 視為可接受）"
            elif lag_s is not None and abs(lag_s) <= 12: verdict = f"**時間錯位 {lag_s:+.1f} s**"
            else: verdict = "**數值與影片不符（非單純錯位）**"
            if "可接受" not in verdict: bad.append((T, r["phase"], Ws, Wv, d, lag_s, verdict))
        L.append(f"| {T} | {r['phase']} | {Ws:.1f} | {'' if Wv is None else f'{Wv:.1f}{star}'} | {'' if d is None else f'{d:+.1f}'} | {'' if lag_s is None else f'{lag_s:+.1f}'} | {verdict} |")
    L += ["", f"需修正列（|diff| > 1.0 g 且 |lag| > 1.5 s 或無法以錯位解釋；不含 time_s=0）：{len(bad)} / {len(flow)}\n"] + NOTES.get(v, {}).get("flow", []) + [""]
    # 溫度
    L += ["## Temperature (upper LCD line = server, lower = outflow)\n",
          "| time_s | sheet server | video upper | Δ | sheet outflow | video lower | Δ |", "|---|---|---|---|---|---|---|"]
    dS, dO = [], []
    for r in therm:
        T = int(r["time_s"]); S = float(r["server_temp_C"]); O = float(r["outflow_temp_C"])
        vs = value_at_timer(rows, "T_upper_server_C", T); vo = value_at_timer(rows, "T_lower_outflow_C", T); star = ""
        if vs is None:
            vs = interp_video(rows, "T_upper_server_C", T); vo = interp_video(rows, "T_lower_outflow_C", T); star = "*"
        if T == 0: vs, vo, star = rows[0]["T_upper_server_C"], rows[0]["T_lower_outflow_C"], "(f1)"
        ds = None if vs is None else round(S - vs, 1); do = None if vo is None else round(O - vo, 1)
        if ds is not None: dS.append(ds)
        if do is not None: dO.append(do)
        L.append(f"| {T} | {S:.1f} | {'' if vs is None else f'{vs:.1f}{star}'} | {'' if ds is None else f'{ds:+.1f}'} | {O:.1f} | {'' if vo is None else f'{vo:.1f}{star}'} | {'' if do is None else f'{do:+.1f}'} |")
    # 溫度最佳時間平移（在 −8..+8 s 內掃描，最小化 RMS）
    def lag_scan(key, col):
        best = None
        for sh in np.arange(-8, 8.01, 0.5):
            e = []
            for r in therm:
                T = int(r["time_s"])
                if T < 10: continue
                vv = interp_video(rows, key, T + sh)
                if vv is not None: e.append(float(r[col]) - vv)
            if len(e) > 5:
                rms = math.sqrt(np.mean(np.square(e)))
                if best is None or rms < best[1]: best = (sh, rms, len(e))
        return best
    ls, lo = lag_scan("T_upper_server_C", "server_temp_C"), lag_scan("T_lower_outflow_C", "outflow_temp_C")
    rms0 = lambda d: math.sqrt(np.mean(np.square(d))) if d else float("nan")
    L += [""] + NOTES.get(v, {}).get("temp", []) + ["", f"- server：RMS(sheet−video, 同一 time_s) = {rms0(dS):.2f} °C；最佳平移 video 取 time_s{ls[0]:+.1f} s 時 RMS = {ls[1]:.2f} °C（n={ls[2]}）",
          f"- outflow：RMS = {rms0(dO):.2f} °C；最佳平移 {lo[0]:+.1f} s 時 RMS = {lo[1]:.2f} °C（n={lo[2]}）", ""]
    # 注水段
    L += ["## Pours detected from video (dW/dt > 0.3 g/s)\n",
          "| # | start (timer, between) | end timer | W before→after (g) | amount (g) | duration (video s) | mean rate (g/s video) | mean rate (g / timer-s) | max 1-s rate (g/s) |",
          "|---|---|---|---|---|---|---|---|---|"]
    for p in P:
        sa = p['start_after_timer_s'] if p['start_after_timer_s'] is not None else ("計時器啟動前" if p['pour'] == 1 else "(過渡格)")
        L.append(f"| {p['pour']} | {sa}–{p['start_by_timer_s']} | {p['end_timer_s']} | {p['W_before_g']:.1f}→{p['W_after_g']:.1f} | {p['amount_g']:.1f} | {p['duration_video_s']:.1f} | {p['mean_rate_gps_video']:.2f} | {p['mean_rate_g_per_timer_s']:.2f} | {p['max_1s_rate_gps']:.1f} |")
    L += ["", "註：第 1 注（悶蒸）在秤計時器顯示 00:00 之前約 0.5–1.5 s 已開始（計時器由重量變化自動觸發）。`start` 欄為「前一個靜止格 – 第一個上升格」的計時器讀值區間，實際起點落在其間。注水率以影片秒計；「g / timer-s」＝除以時鐘速率比 b（紀錄表時間單位）。注水中秤讀值含水柱衝擊力，瞬時速率可能偏高數 g/s。"]
    open(f"{WORK}/vid/{v}_vs_csv.md", "w").write("\n".join(L) + "\n")
    print(f"=== {v} ===  mismatches {len(bad)}/{len(flow)}; pours {len(P)}; server RMS {rms0(dS):.2f} lag {ls}; outflow RMS {rms0(dO):.2f} lag {lo}")
    for b_ in bad: print("   ", b_)
    for p in P: print("   pour", p)
