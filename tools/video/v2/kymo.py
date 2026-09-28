# 以某 x 帶做 kymograph：每格取該帶逐列平均 RGB，橫軸=影格 → 觀察刻度位移與液位上升
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
from common import REPO, WORK, VIDEO_CASES, frame_video_t, log_base, mov_path  # noqa: E402,F401  路徑/時刻慣例見 tools/video/common.py
import sys, glob, numpy as np
from PIL import Image
vid=sys.argv[1]; x0,x1,y0,y1=map(int,sys.argv[2:6]); out=sys.argv[6]; w=int(sys.argv[7]) if len(sys.argv)>7 else 4
fs=sorted(glob.glob(f'{WORK}/vid/{vid}/f_*.jpg'))
cols=[]
for f in fs:
    a=np.asarray(Image.open(f).crop((x0,y0,x1,y1))).astype(float)
    cols.append(a.mean(axis=1))
K=np.stack(cols,axis=1)  # (h, nframes, 3)
K=np.repeat(K,w,axis=1).clip(0,255).astype(np.uint8)
im=Image.fromarray(K)
from PIL import ImageDraw
d=ImageDraw.Draw(im)
for k in range(0,len(fs),10):
    d.line([(k*w,0),(k*w,6)],fill=(255,0,0)); d.text((k*w+1,8),str(k),fill=(255,0,0))
for y in range(((y0+49)//50)*50,y1,50):
    d.line([(0,y-y0),(6,y-y0)],fill=(0,255,0)); d.text((8,y-y0-5),str(y),fill=(0,255,0))
im.save(out)
