"""Fit a camera to manually reviewed, approximate IGN ortho landmarks.

These are image/map correspondences, not surveyed ground control. Never report
the residuals as absolute positioning accuracy. Source preview is a 90° CCW
rotation, resized to 899 x 1200 with PIL pixel-centre mapping.
"""
from pathlib import Path
import json
import cv2
import numpy as np
import rasterio
from scipy.optimize import least_squares, brentq
from project import load_project,resolve,ray_interval

BASE,PROJECT=load_project()
DATA=BASE/'data'
OUT=DATA/'alignment'
OUT.mkdir(exist_ok=True)
ORIGIN=np.array(PROJECT['origin_enu'])
ds=rasterio.open(resolve(BASE,PROJECT,'terrain'))
h=ds.read(1)
sx,sy=ds.res
if ds.transform.b or ds.transform.d or ds.transform.e>=0:raise ValueError('Supply a north-up projected terrain grid')
def height(e,n):
    c=(e-ds.transform.c)/sx-.5;r=(ds.transform.f-n)/sy-.5
    if not(0<=c<h.shape[1]-1 and 0<=r<h.shape[0]-1):raise ValueError('Outside terrain')
    j,i=int(c),int(r);u,v=c-j,r-i
    if u+v<=1:return h[i,j]*(1-u-v)+h[i,j+1]*u+h[i+1,j]*v
    return h[i+1,j+1]*(u+v-1)+h[i,j+1]*(1-v)+h[i+1,j]*(1-u)

points=json.loads(resolve(BASE,PROJECT,'landmarks').read_text())['landmarks']
meta=json.loads(resolve(BASE,PROJECT,'source_manifest').read_text())['sources'][1]
xmin,ymin,xmax,ymax=meta['bounds_lambert93'];rsx=(xmax-xmin)/meta['width'];rsy=(ymax-ymin)/meta['height']
observations=[]
for point in points:
    q=point['reference_px'];e=xmin+(q[0]+.5)*rsx;n=ymax-(q[1]+.5)*rsy
    observations.append({**point,'world_enu':([e,n,float(height(e,n))]-ORIGIN).tolist()})
cal=json.loads(resolve(BASE,PROJECT,'calibration').read_text())
K=np.array(cal['K']);dist=np.array(cal['distortion'])
yaw=np.radians(PROJECT['camera_yaw_prior_deg'])
R0=np.array([[np.cos(yaw),-np.sin(yaw),0],[-np.sin(yaw),-np.cos(yaw),0],[0,0,-1.]])
r0=cv2.Rodrigues(R0)[0].ravel()
train=[p for p in observations if p['role']=='fit']
xyz=np.array([p['world_enu'] for p in train]); uv=np.array([p['image_px'] for p in train])
def project(x,xyz):
    R=cv2.Rodrigues(x[:3])[0];C=x[3:6]
    return cv2.projectPoints(xyz,x[:3],-R@C,K,dist)[0][:,0,:]
def residual(x):return (project(x,xyz)-uv).ravel()
if len(train)<6:raise ValueError('At least six fitting landmarks are required')
fit=least_squares(residual,np.r_[r0,[0,0,PROJECT['camera_height_prior_m']]],loss='soft_l1',f_scale=15,max_nfev=1000)
R=cv2.Rodrigues(fit.x[:3])[0];C=fit.x[3:6]
def unproject(pixel,body_height=0.):
    normalized=cv2.undistortPoints(np.array(pixel,dtype=float).reshape(1,1,2),K,dist)[0,0]
    d=R.T@np.r_[normalized,1.];d/=np.linalg.norm(d)
    if d[2]>=0:raise ValueError('Camera ray is not ground-facing')
    def delta(t):
        p=C+d*t
        return p[2]+ORIGIN[2]-height(p[0]+ORIGIN[0],p[1]+ORIGIN[1])-body_height
    bounds=[ds.bounds.left+sx/2-ORIGIN[0],ds.bounds.right-sx/2-ORIGIN[0],ds.bounds.bottom+sy/2-ORIGIN[1],ds.bounds.top-sy/2-ORIGIN[1]]
    lo,hi=ray_interval(C[:2],d[:2],bounds)
    t=brentq(delta,lo,hi,xtol=1e-9);return C+d*t
for o in observations:
    pred=project(fit.x,np.array([o['world_enu']]))[0]
    o['reprojection_error_px']=float(np.linalg.norm(pred-o['image_px']))
    pos=unproject(o['image_px']);o['horizontal_map_residual_m']=float(np.linalg.norm(pos[:2]-o['world_enu'][:2]))
report={'method':f"Brown intrinsics and terrain-referenced pose; {len(train)} fitting landmarks; {sum(o['role']=='holdout' for o in observations)} held out",
 'source_image':PROJECT['source_image_id'],'origin_enu':ORIGIN.tolist(),'K':K.tolist(),
 'distortion':dist.tolist(),'distortion_status':cal['method'],
 'world_to_camera_R':R.tolist(),'camera_centre_enu':C.tolist(),
 'camera_normal_altitude_m':float(C[2]+ORIGIN[2]),
 'altitude_reference':'Camera height solved against IGN ground, not copied from ambiguous DJI altitude',
 'landmarks':observations,
 'limitations':['Manual map picks are approximate, not surveyed control.',
 'Pond rims and field corners may have changed between captures.',
 'Intrinsics from a small nadir component can retain calibration/height coupling; not survey-calibrated.',
 'Held-out residual measures alignment to this ortho, not absolute survey accuracy.']}
for role in ['fit','holdout']:
    a=np.array([o['horizontal_map_residual_m'] for o in observations if o['role']==role])
    if len(a)==0:raise ValueError('Held-out landmarks are required to report alignment')
    report[role+'_rms_m']=float(np.sqrt(np.mean(a*a)));report[role+'_max_m']=float(max(a))
(OUT/'camera.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items() if k not in ('landmarks','K','world_to_camera_R')},indent=2))
