# 診斷圖：畫出各條帶偵測點（青）、擬合前弧（綠）、推得後弧（洋紅）、刻度（黃）、刻度欄 x_t（白）
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
from common import REPO, WORK, VIDEO_CASES, frame_video_t, log_base, mov_path  # noqa: E402,F401  路徑/時刻慣例見 tools/video/common.py
import sys, json, numpy as np
from PIL import Image, ImageDraw
from level import CFG, vol_of_y
vid=sys.argv[1]; ks=[int(x) for x in sys.argv[2].split(',')]; out=sys.argv[3]
extra = json.load(open(sys.argv[4])) if len(sys.argv)>4 else {}
c=CFG[vid]; R={r['frame']:r for r in json.load(open(f'{WORK}/v2/raw_{vid}.json'))}
xc=(c['xl']+c['xr'])/2; a=(c['xr']-c['xl'])/2
x0,y0,x1,y1=c['xl']-40,max(c['ytop']-40,0),c['xr']+40,c['ybot']+20
tiles=[]
for k in ks:
    im=Image.open(f'{WORK}/vid/{vid}/f_{k:04d}.jpg').crop((x0,y0,x1,y1)); d=ImageDraw.Draw(im); r=R[k]
    for v,y in c['ticks'].items(): d.line([(c['xt']-x0-25,y-y0),(c['xt']-x0-12,y-y0)],fill=(255,255,0),width=2); d.text((c['xt']-x0-50,y-y0-6),str(v),fill=(255,255,0))
    d.line([(c['xt']-x0,0),(c['xt']-x0,y1-y0)],fill=(255,255,255))
    for (px,py) in r.get('pts',[]): d.ellipse([px-x0-2,py-y0-2,px-x0+2,py-y0+2],outline=(0,255,255))
    if 'yc' in r:
        xs=np.linspace(c['xl'],c['xr'],80); u=(xs-xc)/a; s=np.sqrt(np.clip(1-u**2,0,None))
        d.line(list(zip(xs-x0,r['yc']+r['b']*s-y0)),fill=(0,255,0),width=1)
        d.line(list(zip(xs-x0,r['yc']-r['b']*s-y0)),fill=(255,0,255),width=1)
    e=extra.get(str(k),{})
    for key,col in [('y_front',(0,255,0)),('y_foam',(255,160,0)),('y_back',(255,0,255))]:
        if key in e: d.line([(c['xt']-x0-8,e[key]-y0),(c['xt']-x0+30,e[key]-y0)],fill=col,width=3)
    d.rectangle([0,0,160,16],fill=(0,0,0)); d.text((3,3),f'{vid} f{k} t={k-1}s',fill=(255,80,80))
    tiles.append(im)
sc=float(sys.argv[5]) if len(sys.argv)>5 else 0.6
tiles=[t.resize((int(t.width*sc),int(t.height*sc))) for t in tiles]
n=len(tiles); cols=min(n,6); rows=(n+cols-1)//cols
W,H=tiles[0].size; o=Image.new('RGB',(W*cols,H*rows))
for i,t in enumerate(tiles): o.paste(t,((i%cols)*W,(i//cols)*H))
o.save(out)
