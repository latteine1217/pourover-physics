# 以秤計時器讀值（本 agent 目視，整數秒 ±0.5）線性對應 video_t→timer，比較紀錄表
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
from common import REPO, WORK, VIDEO_CASES, frame_video_t, log_base, mov_path  # noqa: E402,F401  路徑/時刻慣例見 tools/video/common.py
import json, sys, csv, numpy as np
from level import CFG, vol_of_y
TIMER={'IMG_3346':[(19,16),(39,36),(59,56),(79,77),(99,97),(119,118)],
       'IMG_3347':[(19,17),(39,37),(59,57),(79,78),(99,98),(119,118)],
       'IMG_3405':[(14,8),(19,13),(39,33),(79,74),(99,94),(119,115)]}
LOG={'IMG_3346':'data/kinu_29_light/4:12/kinu29_light_20g_flow_profile.csv',
     'IMG_3347':'data/kinu_27_light/4:12/kinu27_light_20g_flow_profile.csv',
     'IMG_3405':'data/kinu_28_light/4:20/kinu28_light_20g_flow_profile.csv'}
ROOT=f'{REPO}/'
def timer_map(vid):
    A=np.array(TIMER[vid],float); return np.polyfit(A[:,0],A[:,1],1)
def load_log(vid):
    r=list(csv.DictReader(open(ROOT+LOG[vid])))
    return np.array([[float(x['time_s']),float(x['poured_weight_g']),float(x['drained_volume_ml'])] for x in r])
def series(vid):
    R=json.load(open(f'{WORK}/v2/raw_{vid}.json')); t=CFG[vid]['ticks']
    out=[]
    for r in R:
        yf=[v for v in (r.get('y_front_t',np.nan), r.get('y_direct_corr',np.nan)) if v is not None and np.isfinite(v)]
        y=np.mean(yf) if yf else np.nan
        out.append((r['video_t'], y, float(vol_of_y(y,t)) if np.isfinite(y) else np.nan))
    return np.array(out)
if __name__=='__main__':
    for vid in CFG:
        p=timer_map(vid); S=series(vid); L=load_log(vid)
        tt=np.polyval(p,S[:,0])
        print('===',vid,'timer = %.4f*video_t %+.2f'%tuple(p))
        for ts,pw,dv in L:
            m=np.abs(tt-ts)<0.6
            vf=np.nanmean(S[m,2]) if m.any() else np.nan
            print('  t%5.0f poured %6.1f log %5.1f  Vfront %6.1f  diff %+6.1f'%(ts,pw,dv,vf,dv-vf))
