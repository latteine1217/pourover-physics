"""
彙整逐格結果 → vid/<VID>_level.csv
What: V_liquid_front（真體積讀值）、V_foam_top（前壁泡沫帶頂）、V_side（橢圓中心=輪廓高度，
      「對著前壁刻度讀側緣液線」會得到的值）、V_back_edge（後弧；僅 3347 可直接偵測）。
Why:  紀錄表偏差的候選機制（讀泡沫頂 / 讀側緣 / 讀後緣 / 時間領先）需逐一對照。
"""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
from common import REPO, WORK, VIDEO_CASES, frame_video_t, log_base, mov_path, merge_level_estimators  # noqa: E402,F401  路徑/時刻慣例見 tools/video/common.py
import sys, json, csv, numpy as np
from PIL import Image
from level import CFG, vol_of_y
from compare import timer_map

# 目視覆寫：3347 悶蒸段自動偵測被壺底黑色秤墊橢圓誤導（見報告），改用目視讀值（y_front, px）
# 3347 注水 2–3 段（f48–f68）泡沫毯 + 熱電偶線使自動偵測失效，改以目視每 2 格讀值、其間線性內插
VISUAL_OVERRIDE = {'IMG_3347': {31: 755.0, 46: 752.0, 48: 757.0, 50: 748.0, 52: 741.0, 54: 735.0, 56: 727.0,
                                58: 725.0, 60: 723.0, 62: 713.0, 64: 710.0, 66: 709.0, 68: 705.0},
# 3405 f70–f82：刻度欄內壺底藍色印字 + 注水泡沫團使三個自動估計互相矛盾（spread 10–25 px），改目視
                   'IMG_3405': {70: 711.0, 71: 700.0, 74: 697.0, 76: 686.0, 78: 676.0, 79: 676.0, 80: 674.0, 82: 669.0}}
AUTO_INVALID = {'IMG_3347': range(0, 69), 'IMG_3405': range(70, 83)}   # frame 範圍自動值作廢


def back_arc_3347(k, y_front, x0=1100, x1=1130):
    """3347 後弧（含後壁泡沫帶頂）：自前弧往上，第一段連續 8 列 L>150 的背景（奶油色布/牆）之下緣。"""
    a = np.asarray(Image.open(f'{WORK}/vid/IMG_3347/f_{k:04d}.jpg')).astype(float)[:, x0:x1].mean(1)
    L = a.mean(1); y = int(y_front) - 10; run = 0
    while y > 60:
        run = run+1 if L[y] > 150 else 0
        if run >= 8: return y + 8
        y -= 1
    return np.nan

def _v_or_blank(y, ticks):
    return round(float(vol_of_y(y, ticks)), 1) if np.isfinite(y) else ''

def main(vid):
    c = CFG[vid]; t = c['ticks']; R = json.load(open(f'{WORK}/v2/raw_{vid}.json')); p = timer_map(vid)
    xc = (c['xl']+c['xr'])/2; a = (c['xr']-c['xl'])/2; st = np.sqrt(1-((c['xt']-xc)/a)**2)
    ylow = max(t.values())
    # 平滑 b：只取擬合良好的格
    bs = np.full(len(R), np.nan)
    for i, r in enumerate(R):
        if 'yc' in r and r['fit_rms'] < 6 and r['n_used'] >= 20 and r['b'] > 0 and r['frame'] not in AUTO_INVALID.get(vid, []):
            bs[i] = r['b']
    bsm = np.array([np.nanmedian(bs[max(0,i-5):i+6]) if np.isfinite(bs[max(0,i-5):i+6]).any() else np.nan for i in range(len(R))])
    ytick = np.array([np.nan if r.get('y_tick_direct') is None else r['y_tick_direct'] for r in R], float)
    rows = []
    for i, r in enumerate(R):
        k = r['frame']; q = []
        yfit = r.get('y_front_t', np.nan); ydir = r.get('y_direct_corr', np.nan)
        yfit = np.nan if yfit is None else yfit; ydir = np.nan if ydir is None else ydir
        # 主估計：刻度欄直接量測（無需橢圓修正）；與前後 ±2 格中位數差 >6 px（水柱/反光）時改用另兩估計之平均
        ytk = ytick[i]; nb = ytick[max(0,i-2):i+3]
        rm = np.nanmedian(nb) if np.isfinite(nb).sum() >= 3 else np.nan
        alt = [v for v in (ydir, yfit) if np.isfinite(v)]
        y, q_merge = merge_level_estimators(ytk, ydir, yfit, rm, r.get('wire_px_tick') or 0)
        q += q_merge
        if np.isfinite(y) and alt and max(abs(v-y) for v in alt) > 6: q.append('estimator_spread>6px')
        if k < c['k0']: y = np.nan; q.append('setup')
        if k in AUTO_INVALID.get(vid, []):
            VO = VISUAL_OVERRIDE[vid]; y = VO.get(k, np.nan)
            if np.isfinite(y): q.append('visual_override')
            elif k > 47 and min(VO) < k < max(VO):   # 3347 悶蒸段（<f48）液面不可見，不內插
                ks = sorted(VO); y = float(np.interp(k, ks, [VO[j] for j in ks])); q.append('visual_interp')
            else: q.append('auto_invalid_mat')
        Vf = float(vol_of_y(y, t)) if np.isfinite(y) else np.nan
        if np.isfinite(y) and y > ylow: q.append('low_extrap')
        fp = r.get('foam_px'); fp = np.nan if fp is None else fp
        Vfoam = float(vol_of_y(y-fp, t)) if np.isfinite(y) and np.isfinite(fp) else np.nan
        b = bsm[i]
        yc = y - b*st if np.isfinite(y) and np.isfinite(b) else np.nan
        Vside = float(vol_of_y(yc, t)) if np.isfinite(yc) else np.nan
        yback = np.nan; Vback = np.nan
        if vid == 'IMG_3347' and np.isfinite(y) and k >= 69:
            yback = back_arc_3347(k, y); Vback = float(vol_of_y(yback, t)) if np.isfinite(yback) else np.nan
            if np.isfinite(yback):   # 3347 後弧可直接見：輪廓高度取前/後弧中點（後弧含後壁泡沫帶 → 略偏高）
                yc = (y + yback)/2; Vside = float(vol_of_y(yc, t)); b = (y - yback)/(2*st)
        elif np.isfinite(yc):
            yback = yc - b*st; Vback = float(vol_of_y(yback, t))   # 由橢圓模型推得（霧化，僅供參考）
        if 'yc' in r and (r['fit_rms'] > 8 or r['n_used'] < 20): q.append('ellipse_fit_poor')
        rows.append(dict(frame=k, video_t_s=k-1, timer_est_s=round(float(np.polyval(p, k-1)),2),
            y_front_px=round(y,1) if np.isfinite(y) else '', V_liquid_front_ml=round(Vf,1) if np.isfinite(Vf) else '',
            V_foam_top_ml=round(Vfoam,1) if np.isfinite(Vfoam) else '',
            foam_thickness_ml=round(Vfoam-Vf,1) if np.isfinite(Vfoam) and np.isfinite(Vf) else '',
            V_side_ml=round(Vside,1) if np.isfinite(Vside) else '',
            V_back_edge_ml=round(Vback,1) if np.isfinite(Vback) else '',
            back_edge_source=('direct_3347' if vid=='IMG_3347' and np.isfinite(Vback) else ('ellipse_model' if np.isfinite(Vback) else '')),
            b_smooth_px=round(b,1) if np.isfinite(b) else '', fit_rms_px=round(r['fit_rms'],1) if 'fit_rms' in r else '',
            # 三個獨立估計量（稽核用；合併規則見 WIRE_OCCLUSION_MIN_PX）與遮擋像素數
            V_tick_ml=_v_or_blank(ytk, t), V_strip_ml=_v_or_blank(ydir, t), V_arc_ml=_v_or_blank(yfit, t),
            wire_px_tick=int(r.get('wire_px_tick') or 0),
            quality=';'.join(q) if q else 'ok'))
    # 物理約束：分享壺液量只增不減（僅量測雜訊）。高於後 5 格中位數 >8 mL 或低於前 5 格中位數 >8 mL 者視為偵測突波，作廢
    V = np.array([r['V_liquid_front_ml'] if r['V_liquid_front_ml'] != '' else np.nan for r in rows], float)
    for i, r in enumerate(rows):
        if not np.isfinite(V[i]) or 'visual' in r['quality']: continue
        fut = V[i+1:i+6]; past = V[max(0,i-5):i]
        up = np.isfinite(fut).sum() >= 3 and V[i] - np.nanmedian(fut) > 8
        dn = np.isfinite(past).sum() >= 3 and np.nanmedian(past) - V[i] > 8
        if up or dn:
            for kk in ('y_front_px','V_liquid_front_ml','V_foam_top_ml','foam_thickness_ml','V_side_ml','V_back_edge_ml','back_edge_source'): r[kk] = ''
            r['quality'] = (r['quality'] + ';' if r['quality'] != 'ok' else '') + 'nonmonotone_spike_removed'
    with open(f'{WORK}/vid/{vid}_level.csv','w',newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    print(vid, 'written', len(rows))

if __name__ == '__main__':
    for v in CFG: main(v)
