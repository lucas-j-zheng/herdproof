"""Prepare isolated ODM inputs, conservatively excluding bright animal candidates."""
from pathlib import Path
import json, shutil
import cv2
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
DATA=ROOT/'validation/terrain-demo/data'
manifest=json.loads((DATA/'flight/manifest.json').read_text())
assert manifest['complete'] and len(manifest['images'])==53
out=DATA/'odm/field/images';out.mkdir(parents=True,exist_ok=True)
records=[]
for r in manifest['images']:
    src=DATA/'flight'/r['name'];dst=out/r['name']
    if not dst.exists():shutil.copy2(src,dst)
    im=cv2.imread(str(src)); h,w=im.shape[:2]
    small=cv2.resize(im,(w//4,h//4),interpolation=cv2.INTER_AREA)
    hsv=cv2.cvtColor(small,cv2.COLOR_BGR2HSV)
    bright=((hsv[:,:,2]>185)&(hsv[:,:,1]<65)).astype(np.uint8)
    count,labels,stats,cent=cv2.connectedComponentsWithStats(bright)
    mask=np.full(bright.shape,255,np.uint8)
    for i in range(1,count):
        x,y,bw,bh,area=stats[i]
        if 5<=area<=450 and max(bw,bh)<70:
            cv2.rectangle(mask,(x-6,y-6),(x+bw+6,y+bh+6),0,-1)
    mask=cv2.resize(mask,(w,h),interpolation=cv2.INTER_NEAREST)
    cv2.imwrite(str(out/(src.stem+'_mask.JPG')),mask,[cv2.IMWRITE_JPEG_QUALITY,100])
    records.append({'name':src.name,'masked_fraction':float(np.mean(mask==0))})
(DATA/'odm/preparation.json').write_text(json.dumps({'method':'Conservative bright low-saturation components and 24 px dilation; heuristic moving-animal candidate masks, not verified segmentation', 'images':records},indent=2)+'\n')
print('Prepared 53 original photos and conservative masks',flush=True)
