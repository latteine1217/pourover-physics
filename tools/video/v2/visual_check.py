# 目視判讀（本 agent 讀放大裁切拼圖，y 為 full-res px，判讀點多落在前壁泡沫線/液頂）vs 自動 V_liquid_front
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
from common import REPO, WORK, VIDEO_CASES, frame_video_t, log_base, mov_path  # noqa: E402,F401  路徑/時刻慣例見 tools/video/common.py
import csv, sys, numpy as np
from level import CFG, vol_of_y
VIS={'IMG_3346':{25:665,41:658,47:631,56:611.5,66:581,76:546,86:508,96:464.6,106:431.5,116:376,126:326,136:307},
     'IMG_3347':{71:677,76:655,81:646,86:624.6,91:599,96:587.7,101:564,106:541.5,111:517,116:503,121:474.5,126:447.7,131:416,141:363,150:365},
     'IMG_3405':{21:752,41:749,51:747.5,58:733.8,64:718,70:705.6,78:676,86:658.5,94:631.5,102:600.8,110:568,118:537,126:504.6}}
out=[]
for vid,d in VIS.items():
    rows={int(r['frame']):r for r in csv.DictReader(open(f'{WORK}/vid/{vid}_level.csv'))}; t=CFG[vid]['ticks']
    diffs=[]
    for k,y in d.items():
        va=float(rows[k]['V_liquid_front_ml']) if rows[k]['V_liquid_front_ml'] else np.nan
        vv=float(vol_of_y(y,t)); diffs.append(vv-va)
        out.append(dict(video=vid,frame=k,video_t=k-1,y_visual_px=y,V_visual_ml=round(vv,1),V_auto_ml=round(va,1),diff_visual_minus_auto_ml=round(vv-va,1),quality=rows[k]['quality']))
    dd=np.array(diffs); hi=np.array([vol_of_y(y,t)>=50 for y in d.values()])
    print('%s n=%d  mean %+.1f  sd %.1f  |max| %.1f ; (V>=50: n=%d mean %+.1f sd %.1f)'%(vid,len(dd),np.nanmean(dd),np.nanstd(dd),np.nanmax(np.abs(dd)),hi.sum(),np.nanmean(dd[hi]),np.nanstd(dd[hi])))
with open(f'{WORK}/vid/V2_visual_check.csv','w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=list(out[0].keys())); w.writeheader(); w.writerows(out)
for r in out: print(r['video'][-4:],r['frame'],r['V_visual_ml'],r['V_auto_ml'],r['diff_visual_minus_auto_ml'],r['quality'])
