"""Assess static image/map correspondences and fit a terrain-referenced camera."""
from pathlib import Path
import json
import cv2
import numpy as np
import rasterio
from scipy.ndimage import map_coordinates

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'validation/terrain-demo/data/alignment'
OUT.mkdir(parents=True,exist_ok=True)
raw=cv2.imread(str(ROOT/'validation/data/46472379c810.jpg'))
ref=cv2.imread(str(ROOT/'validation/terrain-demo/data/ign/reference-ortho.jpg'))
scale=2400/raw.shape[1]
small=cv2.resize(raw,None,fx=scale,fy=scale,interpolation=cv2.INTER_AREA)
mask=np.full(small.shape[:2],255,np.uint8)
boxes=json.loads((ROOT/'validation/runs/finetuned/demo.json').read_text())['predictions']
for x1,y1,x2,y2,_ in boxes:
    x1,x2=np.array([x1,x2])*small.shape[1];y1,y2=np.array([y1,y2])*small.shape[0]
    cv2.rectangle(mask,(int(x1)-12,int(y1)-12),(int(x2)+12,int(y2)+12),0,-1)
det=cv2.SIFT_create(nfeatures=20000,contrastThreshold=.015)
k1,d1=det.detectAndCompute(cv2.cvtColor(small,cv2.COLOR_BGR2GRAY),mask)
k2,d2=det.detectAndCompute(cv2.cvtColor(ref,cv2.COLOR_BGR2GRAY),None)
matcher=cv2.BFMatcher()
knn=matcher.knnMatch(d1,d2,k=2)
good=[a for a,b in knn if a.distance<.72*b.distance]
src=np.float32([k1[m.queryIdx].pt for m in good]);dst=np.float32([k2[m.trainIdx].pt for m in good])
print('Keypoints',len(k1),len(k2),'matches',len(good),flush=True)
H,inliers=cv2.findHomography(src,dst,cv2.USAC_MAGSAC,3.0,maxIters=20000,confidence=.999)
if H is None:raise RuntimeError('No consistent reference alignment')
inliers=inliers.ravel().astype(bool)
visual=cv2.drawMatches(small,k1,ref,k2,[m for m,ok in zip(good,inliers) if ok],None,
    flags=cv2.DrawMatchesFlags_NOT_DRAW_SINGLE_POINTS)
cv2.imwrite(str(OUT/'reference-matches.jpg'),visual,[cv2.IMWRITE_JPEG_QUALITY,88])
report={'source':'IGN reference orthophoto, potentially different capture date',
        'working_width':small.shape[1],'matches':len(good),'inliers':int(inliers.sum()),
        'homography_working_to_reference':H.tolist(),
        'correspondences':[{'image_px':(s/scale).tolist(),'reference_px':d.tolist(),'inlier':bool(ok)}
                           for s,d,ok in zip(src,dst,inliers)]}
(OUT/'reference-match-report.json').write_text(json.dumps(report,indent=2)+'\n')
print('Homography inliers',int(inliers.sum()),flush=True)
if inliers.sum()<10:raise RuntimeError('Insufficient reference matches for reliable camera fit; inspect evidence')
