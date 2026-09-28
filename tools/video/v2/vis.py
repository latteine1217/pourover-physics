# 目視判讀拼圖：刻度欄附近放大裁切，只標刻度（黃）與 10 px 格線，不畫自動偵測結果（避免判讀偏誤）
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
from common import REPO, WORK, VIDEO_CASES, frame_video_t, log_base, mov_path  # noqa: E402,F401  路徑/時刻慣例見 tools/video/common.py
import sys, numpy as np
from PIL import Image, ImageDraw
from level import CFG
vid=sys.argv[1]; ks=[int(x) for x in sys.argv[2].split(',')]; ya,yb=int(sys.argv[3]),int(sys.argv[4]); out=sys.argv[5]
c=CFG[vid]; x0,x1=(c["xt"]-170,c["xt"]+50) if len(sys.argv)<7 else map(int,sys.argv[6].split(",")); sc=1.3 if len(sys.argv)<8 else float(sys.argv[7])
tiles=[]
for k in ks:
    im=Image.open(f'{WORK}/vid/{vid}/f_{k:04d}.jpg').crop((x0,ya,x1,yb)); im=im.resize((int(im.width*sc),int(im.height*sc)))
    d=ImageDraw.Draw(im)
    for y in range((ya//10+1)*10,yb,10):
        d.line([(0,(y-ya)*sc),(6 if y%50 else 14,(y-ya)*sc)],fill=(0,255,0))
        if y%50==0: d.text((16,(y-ya)*sc-5),str(y),fill=(0,255,0))
    for v,y in c['ticks'].items():
        if ya<y<yb: d.line([(im.width-12,(y-ya)*sc),(im.width,(y-ya)*sc)],fill=(255,255,0),width=2); d.text((im.width-40,(y-ya)*sc-12),str(v),fill=(255,255,0))
    d.rectangle([0,0,70,12],fill=(0,0,0)); d.text((2,1),f'f{k} t{k-1}',fill=(255,80,80))
    tiles.append(im)
W,H=tiles[0].size; cols=min(len(tiles),7); rows=(len(tiles)+cols-1)//cols
o=Image.new('RGB',(W*cols+4*cols,H*rows+4*rows),'white')
for i,t in enumerate(tiles): o.paste(t,((i%cols)*(W+4),(i//cols)*(H+4)))
o.save(out)
