# 產出 vid/<VID>_level_check.jpg：6 格，標刻度（黃）、條帶偵測點（青點）、刻度欄的前緣（綠）、
# 前壁泡沫頂（橘）、側緣/橢圓中心（青線）、後緣（洋紅），並標 mL
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
from common import REPO, WORK, VIDEO_CASES, frame_video_t, log_base, mov_path  # noqa: E402,F401  路徑/時刻慣例見 tools/video/common.py
import sys, csv, json, numpy as np
from PIL import Image, ImageDraw
from level import CFG, vol_of_y
def y_of_vol(V, ticks):
    ys = np.linspace(0, 1080, 10801); vs = vol_of_y(ys, ticks)
    return float(np.interp(V, vs[::-1], ys[::-1]))
FR={'IMG_3346':[41,56,76,96,116,131],'IMG_3347':[46,71,91,106,121,146],'IMG_3405':[41,64,86,102,116,130]}
for vid,ks in FR.items():
    c=CFG[vid]; t=c['ticks']; rows={int(r['frame']):r for r in csv.DictReader(open(f'{WORK}/vid/{vid}_level.csv'))}
    raw={r['frame']:r for r in json.load(open(f'{WORK}/v2/raw_{vid}.json'))}
    x0,y0,x1,y1=c['xl']-30,max(c['ytop']-20,0),c['xr']+120,c['ybot']+15
    tiles=[]
    for k in ks:
        im=Image.open(f'{WORK}/vid/{vid}/f_{k:04d}.jpg').crop((x0,y0,x1,y1)); d=ImageDraw.Draw(im); r=rows[k]
        for (px,py) in raw[k].get('pts',[]): d.ellipse([px-x0-2,py-y0-2,px-x0+2,py-y0+2],outline=(0,255,255))
        for v,y in t.items(): d.line([(c['xt']-x0-30,y-y0),(c['xt']-x0-16,y-y0)],fill=(255,255,0),width=3)
        xs=c['xt']-x0
        for key,col,lab in [('V_liquid_front_ml',(0,255,0),'front'),('V_foam_top_ml',(255,150,0),'foam'),('V_side_ml',(0,200,255),'side'),('V_back_edge_ml',(255,0,255),'back')]:
            if r[key]:
                V=float(r[key]); y=y_of_vol(V,t)
                if y0<y<y1:
                    d.line([(xs-12,y-y0),(xs+40,y-y0)],fill=col,width=3); d.text((xs+44,y-y0-6),f'{lab} {V:.0f}',fill=col)
        d.rectangle([0,0,230,14],fill=(0,0,0)); d.text((3,2),f'{vid} f{k} video_t={k-1}s timer~{float(r["timer_est_s"]):.0f}s',fill=(255,90,90))
        tiles.append(im)
    sc=0.55; tiles=[im.resize((int(im.width*sc),int(im.height*sc))) for im in tiles]
    W,H=tiles[0].size; o=Image.new('RGB',(W*3,H*2))
    for i,im in enumerate(tiles): o.paste(im,((i%3)*W,(i//3)*H))
    o.save(f'{WORK}/vid/{vid}_level_check.jpg',quality=90); print(vid,o.size)
