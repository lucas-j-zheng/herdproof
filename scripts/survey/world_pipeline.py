"""Upload-to-world worker and offline replay. No field-specific detection snapshots.

Run using the locked terrain interpreter. Native-resolution model inference runs
in the separately locked detector interpreter; image and model hashes bind caches.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import io
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts'))
sys.path.insert(0, str(ROOT/'scripts/terrain'))

import cv2
import numpy as np
from PIL import Image
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import reproject, Resampling
from shapely import contains_xy
from shapely.geometry import Point, Polygon, shape

from world_core import appearance, digest, read, sha, source_image, write
from world_build import copy_viewer
from world_geometry import Terrain
from survey.worlds import code_hash, source_files

VERSION = 'survey-world-1'


def photo_path(job, photo):
    return job/'inputs'/(photo['meta']['byte_sha256']+('.png' if photo['meta']['format']=='PNG' else '.jpg'))


def progress(job, message):
    write(job/'progress.json', {'message': message})
    print(message, flush=True)


def matrix(photo, width, height, origin):
    corners = np.asarray(photo['placement']['corners'], np.float64)-origin
    return cv2.getPerspectiveTransform(np.float32([[0,0],[width,0],[width,height],[0,height]]), corners.astype(np.float32)).astype(float)


def project(points, homography):
    return cv2.perspectiveTransform(np.asarray(points, np.float64).reshape(-1,1,2), homography).reshape(-1,2)


def detections(job, request, offline):
    target = job/'predictions'; lock = job/'predictions.lock.json'
    if lock.exists():
        saved = read(lock)
        for name, expected in saved['files'].items():
            if sha(target/name) != expected:
                raise ValueError('Saved detector output changed; retained predictions failed their integrity check.')
        if saved['model'] != request['model']:
            raise ValueError('Saved predictions belong to another detector configuration.')
        return
    if offline:
        raise ValueError('Offline replay requires saved predictions from a completed build.')
    if read(ROOT/'training/default_model.json') != request['model']:
        raise ValueError('The selected model changed after this job was created. Create a new world to use it.')
    interpreter = ROOT/'.venv/bin/python'
    if not interpreter.is_file():
        raise ValueError('The detector runtime is missing. Install the locked root Python environment before building.')
    progress(job, f"Finding cows in {len(request['batch']['photos'])} original photos…")
    run = subprocess.run([str(interpreter), '-m', 'training.infer', '--data', str(job/'inputs'),
                          '--output', str(target), '--device', 'cpu'], cwd=ROOT, timeout=1800)
    if run.returncode:
        raise ValueError('Cow detection failed. The worker log contains the detector error; retry after fixing the runtime or checkpoint.')
    write(lock, {'model': request['model'], 'files': {p.name: sha(p) for p in sorted(target.glob('*.json'))}})


def terrain_input(job, polygon, offline):
    """Acquire numerical IGN elevation, preferring checksum-bound local coverage.
    Source grids are retained; no flat or synthetic fallback for missing terrain.
    """
    output = job/'terrain.tif'; provenance = job/'terrain-source.json'
    if output.exists() and provenance.exists():
        if sha(output) != read(provenance)['sha256']:
            raise ValueError('Saved terrain failed its integrity check.')
        return
    if offline:
        raise ValueError('Offline replay requires the saved terrain grid.')
    west, south, east, north = polygon.bounds
    west, south, east, north = math.floor(west)-5, math.floor(south)-5, math.ceil(east)+5, math.ceil(north)+5
    width, height = east-west+1, north-south+1
    transform = from_origin(west-.5, north+.5, 1, 1)
    candidates = [ROOT/'validation/terrain-demo/data/ign/terrain.tif', ROOT/'validation/worlds/jalogny-north/ign/terrain.tif']
    source = None
    for candidate in candidates:
        if not candidate.is_file():
            continue
        with rasterio.open(candidate) as ds:
            b = ds.bounds
            if b.left <= west and b.bottom <= south and b.right >= east and b.top >= north:
                source = candidate; break
    provider = {'provider': 'IGN', 'license': 'Licence Ouverte 2.0', 'crs': 'EPSG:2154',
                'vertical_reference': 'IGN NGF-IGN69 product; epoch unresolved',
                'documentation': 'https://cartes.gouv.fr/aide/fr/guides-utilisateur/utiliser-les-services-de-la-geoplateforme/diffusion/wms-raster/'}
    if source is None:
        progress(job, 'Downloading elevation for your field…')
        params = dict(SERVICE='WMS', VERSION='1.3.0', REQUEST='GetMap', STYLES='', CRS='EPSG:2154',
            BBOX=','.join(map(str,[west-.5,south-.5,east+.5,north+.5])), WIDTH=width, HEIGHT=height,
            LAYERS='IGNF_LIDAR-HD_MNT_ELEVATION.ELEVATIONGRIDCOVERAGE.LAMB93', FORMAT='image/geotiff')
        url = 'https://data.geopf.fr/wms-r?'+urllib.parse.urlencode(params)
        source = job/'ign-source.tif'
        try:
            with urllib.request.urlopen(url, timeout=45) as response:
                raw = response.read(32*1024*1024+1)
            if len(raw) > 32*1024*1024 or raw[:2] not in (b'II',b'MM'):
                raise ValueError('IGN did not return a numeric terrain raster.')
            source.write_bytes(raw)
        except (OSError, ValueError) as error:
            raise ValueError('Elevation could not be obtained for this field. Check IGN coverage or retry when the service is available.') from error
        provider['url'] = url
    else:
        # Preserve the actual provider grid for audit and reproduction.
        shutil.copy2(source, job/'ign-source.tif'); source = job/'ign-source.tif'
        provider['acquisition'] = 'Previously acquired local IGN raster covering this boundary'
    with rasterio.open(source) as ds:
        if ds.count != 1 or ds.dtypes[0][0] not in ('f','i','u') or ds.transform.a <= 0 or ds.transform.e >= 0:
            raise ValueError('Unsupported elevation raster.')
        values = ds.read(1, masked=True).astype(np.float32).filled(np.nan)
        array = np.full((height,width), np.nan, np.float32)
        reproject(values, array, src_transform=ds.transform, src_crs='EPSG:2154', src_nodata=np.nan,
                  dst_transform=transform, dst_crs='EPSG:2154', dst_nodata=np.nan, resampling=Resampling.bilinear)
    yy,xx = np.mgrid[:height,:width]
    inside = contains_xy(polygon, west+xx, north-yy)
    if not inside.any() or np.mean(np.isfinite(array[inside])) < .98:
        raise ValueError('Elevation covers less than 98% of this boundary. Choose a covered field; missing terrain is never invented.')
    with rasterio.open(output, 'w', driver='GTiff', width=width, height=height, count=1, dtype='float32',
                       crs='EPSG:2154', transform=transform, nodata=np.nan) as ds:
        ds.write(array,1)
    provider.update(sha256=sha(output), original_sha256=sha(source), resampling='bilinear to 1 m grid', bounds=[west,south,east,north])
    write(provenance, provider)


def linked_pairs(batch):
    """Only a direct, checked background registration authorizes overlap merging."""
    return {frozenset((r['photo_id'],r['reference_id'])) for r in batch['result']['links']}


def merge_observations(rows, batch):
    pairs = linked_pairs(batch)
    photos = {p['id']:p for p in batch['photos']}
    kept = []
    for row in sorted(rows, key=lambda r:(bool(set(r['quality_flags']) & {'insufficient_foreground','segmentation_failed'}),-r['confidence'],r['id'])):
        candidates = []
        for prior in kept:
            if frozenset((row['photo_id'], prior['photo_id'])) not in pairs:
                continue
            times = [datetime.fromisoformat(photos[r['photo_id']]['meta']['captured_local']) for r in (row, prior)]
            if abs((times[1]-times[0]).total_seconds()) > 30:
                continue
            a,b = Polygon(row['map_box']),Polygon(prior['map_box'])
            iou = a.intersection(b).area / max(1e-9,a.union(b).area)
            distance = np.linalg.norm(np.array(row['map_point'])-prior['map_point'])
            if iou >= .5 and distance <= 1.2:
                candidates.append(prior)
        if len(candidates) == 1 and not any(s['photo_id']==row['photo_id'] for s in candidates[0]['sightings']):
            prior = candidates[0]
            row['status'] = 'merged'; row['merge_into'] = prior['id']
            prior['sightings'].append({'id':row['id'],'photo_id':row['photo_id'],'source_image':row['source_image'],'source_crop':row['source_crop']})
            prior['quality_flags'].append('cross_photo_match_needs_review')
        else:
            if candidates:
                row['quality_flags'].append('ambiguous_overlap_kept_separate')
            row['sightings'] = [{'id':row['id'],'photo_id':row['photo_id'],'source_image':row['source_image'],'source_crop':row['source_crop']}]
            kept.append(row)
    return sorted(kept,key=lambda r:r['id'])


def renderable_observations(rows):
    """Keep uncertain evidence without inventing color or displacing crowded cows."""
    kept=[]; footprints=[]
    for row in sorted(rows,key=lambda r:(bool(r['quality_flags']),-r['confidence'],r['id'])):
        if 'insufficient_foreground' in row['quality_flags'] or 'segmentation_failed' in row['quality_flags']:
            row.update(status='appearance_review',exclusion_reason='Cow foreground could not be isolated. Review the original crop before assigning a coat.')
            continue
        x,_,z=row['position']; angle=row['yaw']
        points=np.array([[-.48,-1.1],[.48,-1.1],[.48,1.1],[-.48,1.1]])
        rotation=np.array([[math.cos(angle),math.sin(angle)],[-math.sin(angle),math.cos(angle)]])
        footprint=Polygon(points@rotation.T+[x,z])
        conflict=next((prior for prior,area in footprints if footprint.intersection(area).area>.25),None)
        if conflict:
            row.update(status='placement_review',exclusion_reason='This standing model overlaps another observation. Possible duplicate or resting/crowded cow; retained for review.',conflicts_with=conflict['id'])
            continue
        footprints.append((row,footprint));kept.append(row)
    return sorted(kept,key=lambda r:r['id'])


def assemble(job, request, stage):
    polygon = Polygon(request['parcel']['map_vertices'])
    with rasterio.open(job/'terrain.tif') as ds:
        heights = ds.read(1,masked=True)
        altitude = float(np.ma.median(heights)); window = [0,0,ds.height,ds.width]
    origin = np.array([polygon.centroid.x,polygon.centroid.y])
    terrain = Terrain(job/'terrain.tif', window, [*origin,altitude], 'EPSG:2154')
    yy,xx = np.mgrid[:terrain.h,:terrain.w]
    terrain.valid &= contains_xy(polygon, origin[0]+terrain.min_x+xx, origin[1]-terrain.min_z-yy).astype(np.uint8)
    # Also exclude missing provider cells. Conservative grid edges keep walkers inside.
    terrain.heights.tofile(stage/'heights.bin'); terrain.valid.tofile(stage/'valid.bin')
    span_x,span_z = terrain.max_x-terrain.min_x,terrain.max_z-terrain.min_z
    atlas_size = 2048
    to_atlas = np.array([[ (atlas_size-1)/span_x,0,-terrain.min_x*(atlas_size-1)/span_x],
                         [0,-(atlas_size-1)/span_z,-terrain.min_z*(atlas_size-1)/span_z],[0,0,1]])
    atlas = np.full((atlas_size,atlas_size,3), [118,115,100], np.uint8)
    best = np.zeros((atlas_size,atlas_size),np.float32)
    all_rows = []; photos = []
    (stage/'cows').mkdir(); (stage/'photos').mkdir(); (stage/'assets').mkdir()
    for index, photo in enumerate(request['batch']['photos']):
        progress(job, f"Preparing photo {index+1} of {len(request['batch']['photos'])}: coats, directions and ground…")
        path = photo_path(job,photo); rgb,meta = source_image(path)
        if meta['raw_to_normalized'] != [[1,0,0],[0,1,0],[0,0,1]]:
            raise ValueError('Unsupported camera pixel orientation for automatic placement.')
        h,w = rgb.shape[:2]; H = matrix(photo,w,h,origin)
        image_hash = photo['meta']['byte_sha256']; original = f'photos/{image_hash}{path.suffix}'
        shutil.copy2(path,stage/original)
        prediction = read(job/'predictions'/(image_hash+'.json'))
        if prediction['image_sha256'] != image_hash or prediction['model_sha256'] != request['model']['checkpoint_sha256']:
            raise ValueError('Prediction source or checkpoint hash mismatch.')
        boxes = prediction['modes'][request['model']['mode']]['boxes']
        boxes = sorted([b for b in boxes if b[4]>=request['model']['confidence']],key=lambda b:tuple(b[:4]))
        # Remove detected cows before projecting the ground photograph, including
        # sightings later merged or outside the boundary. Originals remain intact.
        small_w = min(2400,w); small_h = round(h*small_w/w)
        small = cv2.resize(rgb,(small_w,small_h),interpolation=cv2.INTER_AREA)
        repair = np.zeros((small_h,small_w),np.uint8)
        for box in boxes:
            if len(box)!=5 or not np.isfinite(box).all() or min(box)<0 or max(box)>1 or box[2]<=box[0] or box[3]<=box[1]:
                raise ValueError('Invalid normalized detector box.')
            x1,y1,x2,y2 = np.array(box[:4])*[small_w,small_h,small_w,small_h]
            cv2.rectangle(repair,(max(0,int(x1)-3),max(0,int(y1)-3)),(min(small_w-1,math.ceil(x2)+3),min(small_h-1,math.ceil(y2)+3)),255,-1)
            ident = 'C-'+digest({'image':image_hash,'box':box[:4]})[:12].upper()
            raw = {'id':ident,'box':box[:4],'confidence':box[4]}
            proposal,crop,mask = appearance(rgb,raw)
            Image.fromarray(crop).save(stage/'cows'/(ident+'.png'))
            Image.fromarray(mask).save(stage/'cows'/(ident+'-mask.png'))
            centre = np.array([(box[0]+box[2])*w/2,(box[1]+box[3])*h/2])
            point = project([centre],H)[0]
            map_point = point+origin
            theta = math.radians(proposal['axis_degrees']); axis = np.array([math.cos(theta),math.sin(theta)])
            ends = project([centre-axis*5,centre+axis*5],H)
            delta = ends[1]-ends[0]; yaw = float(math.atan2(delta[0],-delta[1]))
            map_box = project(np.array([[box[0],box[1]],[box[2],box[1]],[box[2],box[3]],[box[0],box[3]]])*[w,h],H)+origin
            row = {**raw,**proposal,'sceneCowId':ident,'animalId':None,'trackId':None,'photo_id':photo['id'],
                   'source_image':original,'source_image_sha256':image_hash,'source_crop':f'cows/{ident}.png',
                   'mask_file':f'cows/{ident}-mask.png','source_pixel':centre.tolist(),'map_point':map_point.tolist(),
                   'map_box':map_box.tolist(),'yaw':yaw,'status':'proposed','body_height_assumption_m':0,
                   'heading_status':'ambiguous head/tail; estimated body axis','coat':'Observed foreground color; hidden detail estimated'}
            # A complete standing mesh needs a small interior margin, otherwise its
            # feet can cross an unmeasured or clipped triangle.
            probes = [(point[0]+dx,-point[1]+dz) for dx,dz in [(0,0),(2.2,0),(-2.2,0),(0,2.2),(0,-2.2),(1.6,1.6),(-1.6,1.6),(1.6,-1.6),(-1.6,-1.6)]]
            if not polygon.covers(Point(map_point)):
                row.update(status='outside_boundary',exclusion_reason='Outside the saved field boundary')
            elif not all(np.isfinite(terrain.sample(x,z,True)) for x,z in probes):
                row.update(status='boundary_review',exclusion_reason='Too close to the boundary or missing elevation for safe cow placement')
            else:
                row['position'] = [float(point[0]),float(terrain.sample(point[0],-point[1])),float(-point[1])]
            all_rows.append(row)
        cleaned = cv2.inpaint(small,repair,4,cv2.INPAINT_TELEA) if repair.any() else small
        Hsmall = matrix(photo,small_w,small_h,origin)
        Y,X = np.mgrid[:small_h,:small_w]
        weight = np.minimum.reduce([X+1,small_w-X,Y+1,small_h-Y]).astype(np.float32); weight/=weight.max()
        warped = cv2.warpPerspective(cleaned,to_atlas@Hsmall,(atlas_size,atlas_size))
        weights = cv2.warpPerspective(weight,to_atlas@Hsmall,(atlas_size,atlas_size))
        use = weights>best; atlas[use]=warped[use]; best[use]=weights[use]
        photos.append({'id':photo['id'],'filename':photo['filename'],'source_image':original,'sha256':image_hash,
                       'placement':photo['placement'],'image':meta,'homography_to_local_east_north':H.tolist()})
    cows = renderable_observations(merge_observations([r for r in all_rows if r['status']=='proposed'],request['batch']))
    for index,cow in enumerate(cows): cow['candidate_index']=index
    Image.fromarray(atlas).save(stage/'ground.jpg',quality=94)
    cover = cv2.resize(atlas,(512,512),interpolation=cv2.INTER_AREA)
    observed = cv2.resize((best>0).astype(np.uint8),(512,512),interpolation=cv2.INTER_NEAREST)
    cover[observed==0]=[118,115,100]
    Image.fromarray(cover).save(stage/'landcover.jpg',quality=95)
    Image.fromarray((best>0).astype(np.uint8)*255).save(stage/'observed.png')
    coverage = polygon.intersection(shape(request['batch']['result']['coverage'])).area/polygon.area
    limits = [
        'Automatic draft from uploaded survey images. Cow detections, duplicate matches and apparent coats have not been reviewed.',
        'Image placement uses DJI camera metadata and checked background homographies on a ground plane; draping imagery over elevation does not make it an orthorectified survey.',
        'Positions are approximate; animal motion and camera errors can leave duplicate sightings or incorrect matches. IDs identify observations, not farm animals.',
        'Head direction is unknown. Cow bodies, grass height and hidden surfaces are illustrative. Trees and fences are not reconstructed.',
        f'About {coverage*100:.1f}% of the boundary lies under estimated photo footprints. Unphotographed ground has a neutral texture.',
        'Elevation comes from IGN; source and capture dates may differ. No vertical exaggeration is applied.'
    ]
    scene = {'schema_version':2,'scene_id':job.name,'name':request['parcel']['name'],
             'date':request['batch']['photos'][0]['meta']['captured_local'][:10],'units':'metres',
             'origin':dict(zip(['easting','northing','altitude'],[*origin,altitude])),
             'horizontal_crs':'EPSG:2154','vertical_reference':read(job/'terrain-source.json')['vertical_reference'],
             'terrain':terrain.spec(),'camera':{'method':'DJI metadata and background-linked planar photo placement'},
             'cows':cows,'detectionReview':all_rows,'photos':photos,'fences':[],'trees':[],
             'boundary':[[float(x-origin[0]),float(origin[1]-y)] for x,y in request['parcel']['map_vertices']],
             'vegetation':{'type':'pasture','height_m':.2,'density':.8},
             'procedural_seeds':{'features':9721,'ground_grain':7821,'grass':78231},
             'attributions':[{'name':'Elevation: IGN · Licence Ouverte 2.0','url':'https://cartes.gouv.fr/'},
                             {'name':'Cow mesh: Lyndon Daniels · CC0','url':'https://opengameart.org/content/realtime-ranchers-3d-model-pack'}],
             'limits':limits,'workflow':{'type':'uploaded_survey','read_only':True,'coverage_percent':round(coverage*100,1)},
             'snapshot':digest(request),'review_revision':0,'review_sha256':None}
    for name in ('cow-original.glb','cow-normal.png'):
        shutil.copy2(ROOT/'validation/terrain-demo/assets'/name,stage/'assets'/name)
    write(stage/'scene.json',scene)
    write(stage/'observations.json',{'observations':all_rows,'photos':photos})
    write(stage/'boundary.geojson',{'type':'Feature','properties':{'name':request['parcel']['name'],'sha256':request['parcel']['sha256']},'geometry':request['parcel']['geometry']})
    shutil.copy2(job/'terrain-source.json',stage/'terrain-source.json')
    copy_viewer(stage)
    return scene


def verify(output):
    output = Path(output); manifest=read(output/'build-manifest.json'); scene=read(output/'scene.json')
    for name,expected in manifest['output_sha256'].items():
        path=(output/name).resolve()
        if not path.is_relative_to(output.resolve()) or sha(path)!=expected:
            raise ValueError('Corrupted world output: '+name)
    spec=scene['terrain']; heights=np.fromfile(output/'heights.bin',dtype='<f4').reshape(spec['height'],spec['width'])
    valid=np.fromfile(output/'valid.bin',dtype='u1').reshape(heights.shape)
    if not valid.any() or not np.isfinite(heights).all(): raise ValueError('Invalid world terrain.')
    polygon=Polygon(scene['boundary'])
    ids=set()
    for row in scene['cows']:
        if row['id'] in ids or not polygon.covers(Point(row['position'][0],row['position'][2])):
            raise ValueError('Invalid cow identity or boundary placement.')
        ids.add(row['id'])
    for photo in scene['photos']:
        path=output/photo['source_image']
        if sha(path)!=photo['sha256']: raise ValueError('Original photo integrity failure.')
        rgb,_=source_image(path)
        for row in scene['detectionReview']:
            if row['photo_id']!=photo['id']: continue
            x1,y1,x2,y2=row['crop_bounds']
            if not np.array_equal(rgb[y1:y2,x1:x2],np.asarray(Image.open(output/row['source_crop']))):
                raise ValueError('Source crop no longer matches its original photograph.')
    return {'passed':True,'files_verified':len(manifest['output_sha256']),'source_crops_exact':True,'cows':len(ids)}


def package(job):
    """Private replay archive: source, original inputs, saved model output and vendor files."""
    dest=job/'replay.zip'; prefix=Path('validation/survey-export')/job.name
    members={str(p.relative_to(ROOT)):p for p in source_files()}
    for p in [job/'request.json',job/'inputs.lock.json',job/'predictions.lock.json',job/'terrain.tif',
              job/'terrain-source.json',job/'ign-source.tif',*sorted((job/'inputs').glob('*')),*sorted((job/'predictions').glob('*.json'))]:
        members[str(prefix/p.relative_to(job))]=p
    members[str(prefix/'expected-build-manifest.json')]=job/'build/build-manifest.json'
    for p in (job/'build/vendor').rglob('*'):
        if not p.is_file(): continue
        relative=str(p.relative_to(job/'build/vendor'))
        if relative.startswith('three/'):
            target='validation/terrain-demo/node_modules/'+relative
        elif relative.startswith('rapier/'):
            target='validation/terrain-demo/node_modules/@dimforge/rapier3d-compat/'+relative.removeprefix('rapier/')
        elif relative=='three-LICENSE': target='validation/terrain-demo/node_modules/three/LICENSE'
        elif relative=='rapier-LICENSE': target='validation/terrain-demo/node_modules/@dimforge/rapier3d-compat/LICENSE'
        else: continue
        members[target]=p
    for name in ('cow-original.glb','cow-normal.png'):
        members['validation/terrain-demo/assets/'+name]=job/'build/assets'/name
    # world_build fingerprints all world*.py when imported, but replay imports only
    # the modules listed above. Do not require unrelated calibration tooling.
    instructions=f'''HerdProof uploaded-field replay\n\nThis archive is private and contains original uploaded photographs and GPS metadata.\n\nFrom the extracted root, prepare the locked terrain Python environment once:\n  uv sync --project scripts/terrain --python 3.12.11 --frozen\n\nThen rebuild offline:\n  scripts/terrain/.venv/bin/python scripts/survey/world_pipeline.py --job {prefix} --offline\n\nCompare build/build-manifest.json to expected-build-manifest.json in that job directory.\nEvery output hash should match with the recorded runtime. Browser dependencies and cow assets are included.\nServe the resulting build directory with any static HTTP server.\n\nThe archive includes saved predictions, so replay does not need model weights, the detector runtime or internet.\nInitial generation used the selected checkpoint recorded in request.json.\nPhoto alignment is approximate. All animal observations and head directions remain unreviewed.\n'''
    temp=job/'replay.tmp'
    with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        hashes={}
        for name,path in sorted(members.items()):
            archive.write(path,name);hashes[name]=sha(path)
        archive.writestr('REPLAY.txt',instructions)
        hashes['REPLAY.txt']=__import__('hashlib').sha256(instructions.encode()).hexdigest()
        archive.writestr('bundle-manifest.json',json.dumps({'files':hashes},sort_keys=True))
    temp.replace(dest)
    return {'sha256':sha(dest),'bytes':dest.stat().st_size,'members':len(members)+2}


def run(job, offline=False, output=None):
    started=time.perf_counter(); request=read(job/'request.json')
    if request['code_sha256'] != code_hash():
        raise ValueError('Pipeline code changed after this job was saved. Create a new world to use the current version; replay the saved source bundle for the original.')
    for photo in request['batch']['photos']:
        if sha(photo_path(job,photo))!=photo['meta']['byte_sha256']:
            raise ValueError('Uploaded source photograph changed.')
    detections(job,request,offline)
    progress(job,'Preparing measured elevation for the field boundary…')
    terrain_input(job,Polygon(request['parcel']['map_vertices']),offline)
    input_files=[job/'request.json',job/'terrain.tif',job/'terrain-source.json',job/'ign-source.tif',job/'predictions.lock.json',
                 *sorted((job/'inputs').glob('*')),*sorted((job/'predictions').glob('*.json'))]
    inputs={str(p.relative_to(job)):sha(p) for p in input_files}
    if (job/'inputs.lock.json').exists() and read(job/'inputs.lock.json')!=inputs:
        raise ValueError('A saved world input was modified; replay refused.')
    write(job/'inputs.lock.json',inputs)
    dest=output or job/'build'
    stage=Path(tempfile.mkdtemp(prefix='.build-',dir=job))
    try:
        scene=assemble(job,request,stage)
        progress(job,'Verifying source photos, boundary and world files…')
        hashes={str(p.relative_to(stage)):sha(p) for p in sorted(stage.rglob('*')) if p.is_file()}
        from importlib.metadata import version
        runtime={'python':sys.version.split()[0],'packages':{p:version(p) for p in ('numpy','pillow','opencv-python-headless','rasterio','shapely')}}
        write(stage/'build-manifest.json',{'version':VERSION,'input_sha256':inputs,'source_sha256':code_hash(),'output_sha256':hashes,'runtime':runtime})
        verified=verify(stage)
        previous=None
        if dest.exists():
            if not (dest/'build-manifest.json').is_file() or read(dest/'scene.json')['scene_id']!=job.name: raise ValueError('Refusing to replace an unrelated directory.')
            previous=Path(tempfile.mkdtemp(prefix='.previous-',dir=job));previous.rmdir();dest.replace(previous)
        try: stage.replace(dest)
        except Exception:
            if previous: previous.replace(dest)
            raise
        if previous: shutil.rmtree(previous)
        rows=scene['detectionReview']
        result={'name':scene['name'],'cows':len(scene['cows']),'photos':len(scene['photos']),
                'detections':len(rows),'merged_sightings':sum(r['status']=='merged' for r in rows),
                'outside_boundary':sum(r['status']=='outside_boundary' for r in rows),
                'boundary_review':sum(r['status']=='boundary_review' for r in rows),
                'appearance_review':sum(r['status']=='appearance_review' for r in rows),
                'placement_review':sum(r['status']=='placement_review' for r in rows),
                'appearance_flagged':sum(bool(r['quality_flags']) for r in scene['cows']),
                'unknown_heads':len(scene['cows']),'coverage_percent':scene['workflow']['coverage_percent'],
                'seconds':round(time.perf_counter()-started,2),'verification':verified,'limits':scene['limits'],
                'manifest_sha256':sha(dest/'build-manifest.json')}
        if not offline and output is None:
            progress(job,'Saving the portable replay bundle…')
            result['bundle']=package(job)
        write(job/'result.json',result)
        progress(job,'Your world is ready.')
        return result
    finally:
        if stage.exists(): shutil.rmtree(stage)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job',type=Path,required=True)
    parser.add_argument('--offline',action='store_true')
    parser.add_argument('--output',type=Path)
    parser.add_argument('--verify',action='store_true')
    args=parser.parse_args(); job=args.job.resolve()
    try:
        if args.verify: print(json.dumps(verify(args.output or job/'build')))
        else: print(json.dumps(run(job,args.offline,args.output)))
    except Exception as error:
        write(job/'error.json',{'error':str(error)})
        raise


if __name__=='__main__': main()
