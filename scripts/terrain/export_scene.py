"""Export the measured mesh, camera-projected texture and reviewed observations."""
from pathlib import Path
import json, shutil
import cv2
import numpy as np
import rasterio
from scipy.optimize import brentq
from project import load_project,resolve,ray_interval

BASE,PROJECT=load_project()
DATA=BASE/'data';PUB=Path(PROJECT.get('_output',BASE/'public'));(PUB/'cows').mkdir(parents=True,exist_ok=True)
cam=json.loads((DATA/'alignment/camera.json').read_text())
R=np.array(cam['world_to_camera_R']);C=np.array(cam['camera_centre_enu']);K=np.array(cam['K']);O=np.array(cam['origin_enu'])
dist=np.array(cam['distortion'])
ds=rasterio.open(resolve(BASE,PROJECT,'terrain'));all_h=ds.read(1)
row0,col0,rows,cols=PROJECT['terrain_window'];spacing=ds.res[0]
if ds.transform.b or ds.transform.d or ds.transform.e>=0 or ds.res[0]!=ds.res[1]:raise ValueError('Terrain must be a square-cell, north-up metric raster')
subset=all_h[row0:row0+rows,col0:col0+cols]
if subset.shape!=(rows,cols) or not np.isfinite(subset).all() or np.any(subset==ds.nodata):raise ValueError('Canonical terrain contains missing cells; prepare a valid crop first')
heights=(subset.astype('f8')-O[2]).astype('<f4');heights.tofile(PUB/'heights.bin')
minX=ds.transform.c+(col0+.5)*spacing-O[0];minZ=-(ds.transform.f-(row0+.5)*spacing-O[1]);spanX=(cols-1)*spacing;spanZ=(rows-1)*spacing
def ground(x,z):
    col=(np.asarray(x)-minX)/spacing;row=(np.asarray(z)-minZ)/spacing
    if np.any(col< -1e-5) or np.any(col>cols-1+1e-5) or np.any(row< -1e-5) or np.any(row>rows-1+1e-5):raise ValueError('Outside canonical measured surface')
    j=np.floor(col).astype(int);i=np.floor(row).astype(int)
    j=np.clip(j,0,cols-2);i=np.clip(i,0,rows-2);u=col-j;v=row-i
    a=heights[i,j];b=heights[i,j+1];c=heights[i+1,j];d=heights[i+1,j+1]
    return np.where(u+v<=1,a*(1-u-v)+b*u+c*v,d*(u+v-1)+b*(1-v)+c*(1-u))
def hit(pixel,body=0):
    normalized=cv2.undistortPoints(np.array(pixel,dtype=float).reshape(1,1,2),K,dist)[0,0]
    direction=R.T@np.r_[normalized,1.];direction/=np.linalg.norm(direction)
    def f(t):
        p=C+t*direction;return p[2]-float(ground(p[0],-p[1]))-body
    if direction[2]>=0:raise ValueError('Skyward ray')
    lo,hi=ray_interval([C[0],-C[1]],[direction[0],-direction[1]],[minX,minX+spanX,minZ,minZ+spanZ])
    t=brentq(f,lo,hi,xtol=1e-9);p=C+t*direction
    return [float(p[0]),float(ground(p[0],-p[1])),-float(p[1])]
raw=cv2.imread(str(resolve(BASE,PROJECT,'source_image'))); H,W=raw.shape[:2]
boxes=json.loads(resolve(BASE,PROJECT,'detections').read_text())['predictions']
# Head vectors are visually reviewed in the original-oriented cow contact sheet.
# Low-confidence axes remain explicitly ambiguous, with a reviewer flip in UI.
reviews={x['candidate_index']:x for x in json.loads(resolve(BASE,PROJECT,'cow_review').read_text())['observations']}
if sorted(reviews)!=list(range(1,len(boxes)+1)):raise ValueError('Every detection needs an explicit saved review')
review=[];cows=[]
mask=np.zeros((H,W),np.uint8)
for i,b in enumerate(boxes,1):
    xy=np.array(b[:4])*[W,H,W,H];cx,cy=(xy[:2]+xy[2:])/2
    row={**reviews[i],'box_normalized':b[:4],'confidence':b[4]}
    if row['status']=='accepted':
        body=row['body_height_assumption_m'];anchor=hit([cx,cy],body);d=np.array(row['image_head_vector'],float);d/=np.linalg.norm(d)
        a=np.array(hit([cx,cy]-d*15,body));head=np.array(hit([cx,cy]+d*15,body))
        # Model is later normalized to face +Z; heading measured in browser XZ.
        yaw=float(np.arctan2(head[0]-a[0],head[2]-a[2]))
        name=row['sceneCowId']
        x1,y1,x2,y2=np.round(xy).astype(int);pad=22
        crop=raw[max(0,y1-pad):min(H,y2+pad),max(0,x1-pad):min(W,x2+pad)]
        cv2.imwrite(str(PUB/'cows'/f'{name}.jpg'),crop,[cv2.IMWRITE_JPEG_QUALITY,96])
        cow={**row,'sceneCowId':name,'animalId':None,'trackId':None,'position':anchor,'yaw':yaw,
             'heading_status':row['heading_status'],
             'body_height_assumption_m':body,'source_image':'/source.jpg','source_crop':f'/cows/{name}.jpg',
             'source_pixel':[float(cx),float(cy)],'image_head_vector':d.tolist(),
             'coat':'Observed white/cream; unseen markings estimated','camera_id':PROJECT['source_image_id']}
        cows.append(cow)
    review.append(row)
    if row['status']=='accepted' or 'Duplicate' in row.get('reason',''):
        x1,y1,x2,y2=np.round(xy).astype(int)
        cv2.rectangle(mask,(x1-24,y1-24),(x2+70,y2+35),255,-1)
# Mask publisher boxes solely to remove additional photographed cows from texture.
# They do not create animals or change the detector's accepted population.
reference=json.loads(resolve(BASE,PROJECT,'texture_masks').read_text())['boxes_normalized']
for b in reference:
    if isinstance(b,list) and len(b)>=4:
        x1,y1,x2,y2=np.round(np.array(b[:4])*[W,H,W,H]).astype(int)
        cv2.rectangle(mask,(x1-24,y1-24),(x2+70,y2+35),255,-1)
# Conservative bright-candidate cleanup also covers missed white cattle.
hsv=cv2.cvtColor(raw,cv2.COLOR_BGR2HSV);bright=((hsv[:,:,2]>210)&(hsv[:,:,1]<55)).astype(np.uint8)
n,lab,stats,_=cv2.connectedComponentsWithStats(bright)
for x,y,w,h,area in stats[1:]:
    if 70<area<4500 and max(w,h)<180:
        cv2.rectangle(mask,(x-18,y-18),(x+w+65,y+h+35),255,-1)
# Fill is inferred appearance, never used for detection or geometry.
small=cv2.resize(raw,(W//2,H//2),interpolation=cv2.INTER_AREA)
smask=cv2.resize(mask,(W//2,H//2),interpolation=cv2.INTER_NEAREST)
clean=cv2.inpaint(small,smask,9,cv2.INPAINT_TELEA)
cv2.imwrite(str(PUB/'texture-repair-mask.png'),cv2.resize(mask,(1320,round(H/W*1320)),interpolation=cv2.INTER_NEAREST))
ref=cv2.imread(str(resolve(BASE,PROJECT,'reference_ortho')))
xmin,ymin,xmax,ymax=PROJECT['reference_bounds'];ref_sx=(xmax-xmin)/ref.shape[1];ref_sy=(ymax-ymin)/ref.shape[0]
size=PROJECT['atlas_resolution'];atlas=np.zeros((size,size,3),np.uint8);observed=np.zeros((size,size),np.uint8)
for row in range(0,size,128):
    zs=minZ+(np.arange(row,min(size,row+128))+.5)*spanZ/size
    xs=minX+(np.arange(size)+.5)*spanX/size;x,z=np.meshgrid(xs,zs);y=ground(x,z)
    xyz=np.stack([x,-z,y],axis=-1);q=np.einsum('...j,ij->...i',xyz-C,R,optimize=False)
    assert np.isfinite(q).all(), 'Nonfinite camera projection'
    qx=q[:,:,0]/q[:,:,2];qy=q[:,:,1]/q[:,:,2];r2=qx*qx+qy*qy
    k1,k2,p1,p2,k3=dist;radial=1+k1*r2+k2*r2*r2+k3*r2*r2*r2
    dx=qx*radial+2*p1*qx*qy+p2*(r2+2*qx*qx)
    dy=qy*radial+p1*(r2+2*qy*qy)+2*p2*qx*qy
    u=(K[0,0]*dx+K[0,2]).astype(np.float32)
    v=(K[1,1]*dy+K[1,2]).astype(np.float32)
    valid=(u>=0)&(u<W-1)&(v>=0)&(v<H-1)&(q[:,:,2]>0)
    sample=cv2.remap(clean,((u+.5)*clean.shape[1]/W-.5).astype('f4'),((v+.5)*clean.shape[0]/H-.5).astype('f4'),cv2.INTER_LINEAR,borderMode=cv2.BORDER_REFLECT)
    refu=((x+O[0]-xmin)/ref_sx-.5).astype('f4');refv=((ymax-(-z+O[1]))/ref_sy-.5).astype('f4')
    background=cv2.remap(ref,refu,refv,cv2.INTER_LINEAR)
    # Smooth only the image boundary, not the underlying elevations.
    edge=np.minimum.reduce([u,W-1-u,v,H-1-v]);weight=np.clip(edge/90,0,1)[:,:,None]
    atlas[row:row+len(zs)]=(sample*weight+background*(1-weight)).astype('u1')
    observed[row:row+len(zs)]=valid*255
cv2.imwrite(str(PUB/'ground.jpg'),atlas,[cv2.IMWRITE_JPEG_QUALITY,94])
cv2.imwrite(str(PUB/'observed.png'),cv2.resize(observed,(1024,1024),interpolation=cv2.INTER_NEAREST))
vegetation=cv2.resize(atlas,(512,512),interpolation=cv2.INTER_AREA)
cv2.imwrite(str(PUB/'landcover.jpg'),vegetation,[cv2.IMWRITE_JPEG_QUALITY,97])
shutil.copy2(resolve(BASE,PROJECT,'source_image'),PUB/'source.jpg')
features=json.loads(resolve(BASE,PROJECT,'features').read_text())
def placed(points):return [hit(p) for p in points]
scene={'schema_version':1,'name':PROJECT['name'],'title':PROJECT['name']+' · a measured field','date':PROJECT['captured'],'reference_bounds':PROJECT['reference_bounds'],
 'origin':{'easting':O[0],'northing':O[1],'altitude':O[2]},'horizontal_crs':PROJECT['horizontal_crs'],
 'vertical_reference':PROJECT['vertical_reference'],'units':'metres',
 'terrain':{'width':cols,'height':rows,'spacing':spacing,'minX':minX,'minZ':minZ,'verticalExaggeration':1,
            'file':'/heights.bin','diagonal':'top-right to bottom-left','minAltitude':float(heights.min()+O[2]),'maxAltitude':float(heights.max()+O[2]),
            'source_sha256':json.loads(resolve(BASE,PROJECT,'source_manifest').read_text())['sources'][0]['sha256']},
 'camera':cam,'cows':cows,'detectionReview':review,'referenceCount':PROJECT['reference_count'],
 'fences':[placed(p) for p in features['fences']],
 'trees':[{**t,'position':hit(t['source_pixel'])} for t in features['trees']],
 'pond':{**features['pond'],'position':hit(features['pond']['source_pixel'])},
 'repair':{'method':'Local inpainting of cattle/shadow candidate masks; inferred ground appearance','publisher_boxes_used_for_mask_only':len(reference),'masked_source_fraction':float(np.mean(mask>0))},
 'attributions':PROJECT['attributions'],'limits':PROJECT['limits']}
(PUB/'scene.json').write_text(json.dumps(scene,indent=2)+'\n')
stride=PROJECT['outer_terrain_stride'];outer=(all_h[::stride,::stride].astype('f8')-O[2]).astype('<f4')
scene['outerTerrain']={'width':outer.shape[1],'height':outer.shape[0],'spacing':spacing*stride,'minX':ds.transform.c+.5*spacing-O[0],'minZ':-(ds.transform.f-.5*spacing-O[1]),
 'note':'Measured vertex samples at 2m for distant context only, outside walk boundary'}
outer.tofile(PUB/'outer-heights.bin')
shutil.copy2(resolve(BASE,PROJECT,'reference_ortho'),PUB/'reference.jpg')
(PUB/'scene.json').write_text(json.dumps(scene,indent=2)+'\n')
(DATA/'detection-review.json').write_text(json.dumps(review,indent=2)+'\n')
print(f'Exported {len(cows)} accepted cows, {cols} x {rows} measured grid, {size}px texture; repair fraction {np.mean(mask>0):.3f}',flush=True)
