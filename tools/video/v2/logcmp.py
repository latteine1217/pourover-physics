# 紀錄表 vs 影片：以計時器對應內插；輸出逐列比較與分段統計
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
from common import REPO, WORK, VIDEO_CASES, frame_video_t, log_base, mov_path  # noqa: E402,F401  路徑/時刻慣例見 tools/video/common.py
import csv, sys, numpy as np
from compare import load_log, LOG, ROOT
def col(rows,k): return np.array([float(r[k]) if r[k]!='' else np.nan for r in rows])
out=[]
for vid in ['IMG_3346','IMG_3347','IMG_3405']:
    rows=list(csv.DictReader(open(f'{WORK}/vid/{vid}_level.csv')))
    T=col(rows,'timer_est_s'); C={k:col(rows,k) for k in ['V_liquid_front_ml','V_foam_top_ml','V_side_ml','V_back_edge_ml']}
    phases=[r['phase'] for r in csv.DictReader(open(ROOT+LOG[vid]))]
    L=load_log(vid); print('===',vid)
    print('  t_s  phase              poured  log   front  foam  side  back | log-front log-side')
    for (ts,pw,dv),ph in zip(L,phases):
        vals={}
        for k,v in C.items():
            m=np.isfinite(v)&(np.abs(T-ts)<=1.5)
            vals[k]=np.interp(ts,T[m],v[m]) if m.sum()>=2 else np.nan
        f=vals['V_liquid_front_ml']
        print('  %4.0f %-18s %6.1f %5.1f  %6.1f %5.1f %5.1f %5.1f | %+6.1f %+6.1f'%(ts,ph,pw,dv,f,vals['V_foam_top_ml'],vals['V_side_ml'],vals['V_back_edge_ml'],dv-f,dv-vals['V_side_ml']))
        out.append(dict(video=vid,time_s=ts,phase=ph,poured_g=pw,log_drained_ml=dv,**{k:round(v,1) if np.isfinite(v) else '' for k,v in vals.items()},
                        log_minus_front=round(dv-f,1) if np.isfinite(f) else ''))
with open(f'{WORK}/vid/V2_log_vs_video.csv','w',newline='') as fh:
    w=csv.DictWriter(fh,fieldnames=list(out[0].keys())); w.writeheader(); w.writerows(out)
