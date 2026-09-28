# 假設檢定：紀錄表 drained 與各候選讀值之 RMS；時間領先 τ；比例因子；隱含床內保水
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
from common import REPO, WORK, VIDEO_CASES, frame_video_t, log_base, mov_path  # noqa: E402,F401  路徑/時刻慣例見 tools/video/common.py
import csv, sys, numpy as np
from compare import load_log
RHO=0.98   # 60–80 °C 咖啡液密度 g/mL（水 0.972–0.983 + TDS 1.3% 約 +0.005）
for vid in ['IMG_3346','IMG_3347','IMG_3405']:
    rows=list(csv.DictReader(open(f'{WORK}/vid/{vid}_level.csv')))
    T=np.array([float(r['timer_est_s']) for r in rows]); F=np.array([float(r['V_liquid_front_ml'] or 'nan') for r in rows])
    m=np.isfinite(F); T,F=T[m],F[m]
    cmp=[r for r in csv.DictReader(open(f'{WORK}/vid/V2_log_vs_video.csv')) if r['video']==vid]
    def arr(k): return np.array([float(r[k]) if r[k] else np.nan for r in cmp])
    t=arr('time_s'); lg=arr('log_drained_ml'); pw=arr('poured_g')
    sel=(t>=45)&(lg>0)&(np.array([r['phase'] for r in cmp])!='flow_stop_visual')
    print('===',vid,'n=%d (t>=45)'%sel.sum())
    for k in ['V_liquid_front_ml','V_foam_top_ml','V_side_ml','V_back_edge_ml']:
        d=(lg-arr(k))[sel]; d=d[np.isfinite(d)]
        print('  %-18s mean %+6.1f  RMS %5.1f  min %+6.1f max %+6.1f (n=%d)'%(k,d.mean(),np.sqrt((d**2).mean()),d.min(),d.max(),len(d)))
    best=None
    for tau in np.arange(0,30.1,0.5):
        v=np.interp(t+tau,T,F,right=np.nan); d=(lg-v)[sel]; d=d[np.isfinite(d)]
        if len(d)<sel.sum()-4: continue
        r=np.sqrt((d**2).mean())
        if best is None or r<best[1]: best=(tau,r,d.mean(),len(d))
    print('  time-lead: best tau %.1f s, RMS %.1f, mean %+.1f (n=%d)'%best)
    f=arr('V_liquid_front_ml'); mm=sel&np.isfinite(f)
    kfac=(lg[mm]@f[mm])/(f[mm]@f[mm]); d=lg[mm]-kfac*f[mm]
    print('  scale model log=k*front: k=%.3f RMS %.1f'%(kfac,np.sqrt((d**2).mean())))
    # 隱含保水
    for lab,V in [('log',lg),('video_front',f)]:
        R=pw-RHO*V
        print('  retention[%s] last rows:'%lab, ' '.join('%d:%.1f'%(a,b) for a,b in zip(t[-4:],R[-4:])))
    print('  video plateau: last 5 frames mean V_front %.1f, span timer %.1f–%.1f'%(F[-5:].mean(),T[-5],T[-1]))
