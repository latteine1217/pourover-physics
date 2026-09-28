"""
V2 液位量測：分享壺液面前緣（front contact line）自動偵測 + 橢圓模型。
What: 逐格在壺內多條垂直條帶找「咖啡液」連續區頂端（液面與前壁交線），
      以投影圓（橢圓前弧 y = yc + b*sqrt(1-u^2)）擬合得 yc（輪廓高度）與 b（半短軸），
      在刻度欄位 x_t 取前弧 y 值，以同欄刻度線 y 做分段線性 y→mL。
Why:  刻度印在前壁，液面在同一方位角與前壁的交點和同高度刻度在影像中重合 →
      與相機俯角無關（透視自動抵消）；輪廓高度/後弧只作「誤讀情境」對照。
"""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
from common import REPO, WORK, VIDEO_CASES, frame_video_t, log_base, mov_path  # noqa: E402,F401  路徑/時刻慣例見 tools/video/common.py
import sys, glob, json, numpy as np
from PIL import Image

CFG = {
 'IMG_3346': dict(k0=12, xl=1015, xr=1455, xt=1318, ytop=90, ybot=668, xs_band=(1255,1280), xt_band=(1312,1332),
     ticks={50:622,100:553.5,150:481,200:406,250:327,300:245.5,350:160}),
 'IMG_3347': dict(k0=10, xl=944, xr=1399, xt=1218, ytop=60, ybot=760, xs_band=(1150,1180), xt_band=(1200,1225),
     ticks={50:725,100:652,150:575,200:497,250:416,300:331,350:244,400:151,450:57}),
 'IMG_3405': dict(k0=9, xl=795, xr=1120, xt=935, ytop=270, ybot=762, xs_band=(885,905), xt_band=(938,952),
     ticks={50:731,100:684,150:634,200:580,250:521.5,300:457.5,350:386,400:311.5}),
}

def vol_of_y(y, ticks):
    """刻度分段線性 y→mL；超出最低刻度以 50–100 段斜率線性外插（低量段不確定）。"""
    ys = np.array(sorted(ticks.values()))[::-1]          # 由下(大y)到上
    vs = np.array([v for v,_ in sorted(ticks.items(), key=lambda t:-t[1])])
    y = np.asarray(y, float)
    out = np.interp(-y, -ys, vs)
    lo = y > ys[0]; s = (vs[1]-vs[0])/(ys[0]-ys[1])
    out = np.where(lo, vs[0] - (y-ys[0])*s, out)
    hi = y < ys[-1]; s2 = (vs[-1]-vs[-2])/(ys[-2]-ys[-1])
    out = np.where(hi, vs[-1] + (ys[-1]-y)*s2, out)
    return out

def dVdy(y, ticks, h=2.0):
    return (vol_of_y(y-h,ticks)-vol_of_y(y+h,ticks))/(2*h)  # mL per px (正值)

def coffee_mask(a):
    R,G,B = a[...,0],a[...,1],a[...,2]; L = a.mean(-1)
    # 深色且不偏藍（排除藍色熱電偶線）或 明亮但強烈偏紅（背光處的紅棕液體；排除黃色水柱 R/G~1.3）
    # 第三項：受光的紅棕液體（L 45–90，R 明顯高於 G、B），3346 末段背光處需要
    return ((L < 45) & (R >= B+4) & (R >= G)) | ((R > 2*G) & (R-B > 30)) | ((L < 90) & (R-G > 20) & (R-B > 20))

def foam_mask(a):
    R,G,B = a[...,0],a[...,1],a[...,2]; L = a.mean(-1)
    return (L > 80) & (R-B > 10) & (R < 1.6*G)

def front_in_band(C, y0, win=20, thr=0.75):
    """C: 該條帶逐列咖啡比例。回傳液體連續區頂端（次像素，c 由下往上跌破 0.5 處）。"""
    n = len(C)
    if n < win: return np.nan
    cs = np.concatenate([[0], np.cumsum(C)])
    s = (cs[win:] - cs[:-win]) / win
    idx = np.where(s >= thr)[0]
    if len(idx) == 0: return np.nan
    i = idx[0]
    # 在 [i-6, i+win) 找 c 由 <0.5 到 >=0.5 的最上交界
    j0 = max(i-6, 0)
    for j in range(j0, min(i+win, n-1)):
        if C[j] < 0.5 <= C[j+1]:
            return y0 + j + (0.5 - C[j])/(C[j+1]-C[j]) + 0.5
    return y0 + i

def fit_ellipse_front(xs, ys, xc, a):
    """固定 xc, a，以 IRLS-Huber 擬合 y = yc + b*sqrt(1-u^2)。回傳 yc, b, rms, n_used"""
    u = (xs - xc)/a; w_ = np.sqrt(np.clip(1-u**2, 0, None))
    A = np.stack([np.ones_like(u), w_], 1); wt = np.ones_like(u)
    for _ in range(10):
        sol,*_ = np.linalg.lstsq(A*wt[:,None], ys*wt, rcond=None)
        r = ys - A@sol
        s = 1.4826*np.median(np.abs(r)) + 0.5
        wt = np.sqrt(np.minimum(1, 2.5*s/np.maximum(np.abs(r),1e-9)))
    good = np.abs(r) < 3*s
    return sol[0], sol[1], float(np.sqrt(np.mean(r[good]**2))), int(good.sum())

# ── 刻度欄遮擋偵測（F12a，2026-09-27）────────────────────────────────────────
# What: 在刻度欄條帶（左右各放寬 WIRE_BAND_PAD_PX）、刻度欄液面前緣上方 WIRE_WIN_ABOVE_PX
#       到下方 2 px 的窗內，數「熱電偶線藍」像素（B > R + 50 且 B > G + 30）。
# Why:  分享壺內垂下的熱電偶線在液面處被液體沿線爬升的彎液面包覆；線穿過刻度欄時，
#       刻度欄的「液體連續區頂端」會沿線被抬高（IMG_3347 f107–f130：刻度欄估計比另兩個
#       估計高 2–5 mL）。露出液面的線段是飽和藍（實測 (17,69,127)、(48,74,123)），
#       咖啡液、泡沫、刻度與霧化壁面都不滿足此色域（背景最藍者 (52,67,96) 仍差 > 20）。
#       三支影片全格掃描：只有 IMG_3347 f107–f130 與 setup 格（f1–f11）有 ≥ 20 px 命中。
WIRE_BAND_PAD_PX = 10
WIRE_WIN_ABOVE_PX = 60


def wire_px_near_front(im, xt_band, y_front):
    """刻度欄前緣上方窗內的熱電偶線像素數（遮擋判據；門檻見 finalize.WIRE_OCCLUSION_MIN_PX）。"""
    if not np.isfinite(y_front):
        return 0
    t0, t1 = xt_band
    y0 = max(int(y_front) - WIRE_WIN_ABOVE_PX, 0)
    b = im[y0:int(y_front) + 3, t0 - WIRE_BAND_PAD_PX:t1 + WIRE_BAND_PAD_PX]
    return int(((b[..., 2] > b[..., 0] + 50) & (b[..., 2] > b[..., 1] + 30)).sum())


def process(vid):
    c = CFG[vid]; files = sorted(glob.glob(f'{WORK}/vid/{vid}/f_*.jpg'))
    xc = (c['xl']+c['xr'])/2; a = (c['xr']-c['xl'])/2
    bx = np.arange(c['xl']+0.035*2*a, c['xr']-0.035*2*a, 8).astype(int)
    rows = []
    for f in files:
        k = int(f[-8:-4])
        im = np.asarray(Image.open(f)).astype(np.float32)
        sub = im[c['ytop']:c['ybot']]
        pts = []
        for x in bx:
            C = coffee_mask(sub[:, x:x+5]).mean(1)
            yf = front_in_band(C, c['ytop'])
            if np.isfinite(yf): pts.append((x+2.5, yf))
        rec_pts = pts
        # 刻度旁直接條帶
        x0,x1 = c['xs_band']
        Cb = coffee_mask(sub[:, x0:x1]).mean(1)
        yb_direct = front_in_band(Cb, c['ytop'])
        # 前壁泡沫帶：直接條帶液頂上方連續的淺褐色列數
        foam_px = np.nan
        if np.isfinite(yb_direct):
            Fm = foam_mask(sub[:, x0:x1]).mean(1)
            j = int(round(yb_direct)) - c['ytop'] - 1; n = 0; gap = 0
            while j >= 0 and n + gap < 80:
                if Fm[j] >= 0.5: n += 1 + gap; gap = 0
                elif gap < 2: gap += 1
                else: break
                j -= 1
            foam_px = n
        # 刻度欄本身（遮蔽刻度線列 ±4 px 後內插），免除橢圓斜率修正
        t0,t1 = c['xt_band']
        Ct = coffee_mask(sub[:, t0:t1]).mean(1).astype(float)
        yy = np.arange(len(Ct)) + c['ytop']; msk = np.zeros(len(Ct), bool)
        for ty in c['ticks'].values(): msk |= np.abs(yy-ty) <= 4
        if (~msk).sum() > 10: Ct[msk] = np.interp(yy[msk], yy[~msk], Ct[~msk])
        y_tick_direct = front_in_band(Ct, c['ytop'])
        rec = dict(y_tick_direct=y_tick_direct, pts=rec_pts, frame=k, video_t=k-1, n_pts=len(pts), y_direct=yb_direct, foam_px=foam_px,
                   wire_px_tick=wire_px_near_front(im, c['xt_band'], y_tick_direct))
        if len(pts) >= 8:
            P = np.array(pts); yc,b,rms,nu = fit_ellipse_front(P[:,0], P[:,1], xc, a)
            ut = (c['xt']-xc)/a; st = np.sqrt(1-ut**2)
            ub = ((x0+x1)/2 - xc)/a; sb = np.sqrt(1-ub**2)
            rec.update(yc=yc, b=b, fit_rms=rms, n_used=nu,
                       y_front_t=yc + b*st, y_back_t=yc - b*st,
                       y_direct_corr=yb_direct + b*(st-sb) if np.isfinite(yb_direct) else np.nan)
        rows.append(rec)
    return rows

if __name__ == '__main__':
    vid = sys.argv[1]
    rows = process(vid)
    json.dump(rows, open(f'{WORK}/v2/raw_{vid}.json','w'), default=float)
    print(vid, len(rows))
