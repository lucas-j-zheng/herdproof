"""Independent validation of exported heights, camera projection and identities."""
from pathlib import Path
import json, hashlib
import cv2
import numpy as np
import rasterio
from project import load_project,resolve

base,project=load_project();out=Path(project.get('_output',base/'public'))
s=json.loads((out/'scene.json').read_text());spec=s['terrain'];origin=np.array(project['origin_enu'])
with rasterio.open(resolve(base,project,'terrain')) as ds:
    r,c,rows,cols=project['terrain_window'];source=ds.read(1)[r:r+rows,c:c+cols].astype('f8')
    exported=np.fromfile(out/'heights.bin',dtype='<f4').reshape(rows,cols)
    expected_minx=ds.transform.c+(c+.5)*ds.res[0]-origin[0]
    expected_minz=-(ds.transform.f-(r+.5)*ds.res[1]-origin[1])
    assert spec['minX']==expected_minx and spec['minZ']==expected_minz
    error=float(np.max(np.abs(exported.astype('f8')+origin[2]-source)))
    assert error<1e-5, f'Changed source heights by {error} m'
    assert spec['verticalExaggeration']==1 and spec['spacing']==ds.res[0]
camera=s['camera'];R=np.array(camera['world_to_camera_R']);C=np.array(camera['camera_centre_enu']);K=np.array(camera['K']);dist=np.array(camera['distortion'])
assert np.max(np.abs(R.T@R-np.eye(3)))<1e-10 and abs(np.linalg.det(R)-1)<1e-10
max_pixel=0
for cow in s['cows']:
    x,y,z=cow['position'];body=cow['body_height_assumption_m']
    point=np.array([[x,-z,y+body]],float)
    pixel=cv2.projectPoints(point,cv2.Rodrigues(R)[0],-R@C,K,dist)[0][0,0]
    max_pixel=max(max_pixel,float(np.linalg.norm(pixel-cow['source_pixel'])))
    assert cow['animalId'] is None and cow['trackId'] is None
    assert (out/cow['source_crop'].lstrip('/')).exists()
assert max_pixel<.05,f'Camera inversion error {max_pixel} px'
ids=[c['sceneCowId'] for c in s['cows']];assert len(ids)==len(set(ids))
review=json.loads(resolve(base,project,'cow_review').read_text())['observations']
assert set(ids)=={c['sceneCowId'] for c in review if c['status']=='accepted'}
assert hashlib.sha256((out/'source.jpg').read_bytes()).hexdigest()==hashlib.sha256(resolve(base,project,'source_image').read_bytes()).hexdigest()
report={'passed':True,'height_samples':rows*cols,'source_height_max_error_m':error,'pixel_centres_and_axes_correct':True,'body_anchor_round_trip_max_error_px':max_pixel,'accepted_scene_ids':ids,'source_photo_unchanged':True,'camera_alignment_fit_rms_m':camera['fit_rms_m'],'camera_alignment_holdout_rms_m':camera['holdout_rms_m'],'camera_accuracy_limit':'Projection consistency is not survey accuracy; retain independent map residuals.'}
(out/'geometry-validation.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
