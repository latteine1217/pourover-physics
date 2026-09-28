# 用法: crop.py VID k x0 y0 x1 y1 out [scale]
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
from common import REPO, WORK, VIDEO_CASES, frame_video_t, log_base, mov_path  # noqa: E402,F401  路徑/時刻慣例見 tools/video/common.py
import sys
from PIL import Image, ImageDraw
vid,k=sys.argv[1],int(sys.argv[2]); x0,y0,x1,y1=map(int,sys.argv[3:7]); out=sys.argv[7]
sc=float(sys.argv[8]) if len(sys.argv)>8 else 1.0
im=Image.open(f'{WORK}/vid/{vid}/f_{k:04d}.jpg').crop((x0,y0,x1,y1))
im=im.resize((int(im.width*sc),int(im.height*sc)))
d=ImageDraw.Draw(im)
# 每 20 px 標格線 y 座標（full-res）
for y in range(((y0+19)//20)*20,y1,20):
    yy=(y-y0)*sc; d.line([(0,yy),(8 if y%100 else 20,yy)],fill=(255,0,0)); 
    if y%100==0: d.text((22,yy-6),str(y),fill=(255,0,0))
for x in range(((x0+19)//20)*20,x1,20):
    xx=(x-x0)*sc; d.line([(xx,0),(xx,8 if x%100 else 20)],fill=(0,255,0))
    if x%100==0: d.text((xx+2,22),str(x),fill=(0,255,0))
im.save(out)
