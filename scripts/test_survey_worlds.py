"""Production-flow contracts: immutable jobs, real geometry, replay and failures."""
import copy
import io
from PIL import Image, ImageDraw, PngImagePlugin
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import Polygon

sys.path.insert(0,str(Path(__file__).parent/'terrain'))
from survey.batch import Batches
from survey.core import Store, FROM_MAP, canonical, digest
from survey.worlds import Worlds, code_hash
from survey.world_pipeline import run, verify, matrix, project, merge_observations, renderable_observations
from world_core import sha, write
from test_survey_batch import drone


class WorldTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
        self.store=Store(self.root); self.batches=Batches(self.store);self.worlds=Worlds(self.store,self.batches,start_worker=False)
        batch=self.batches.create();self.batch_id=batch['id'];self.batches.add(self.batch_id,self.cow_photo(), 'input.png')
        self.batches.build(self.batch_id)
        deadline=time.monotonic()+5
        while self.batches.get(self.batch_id)['status']=='building' and time.monotonic()<deadline:time.sleep(.01)
        self.batch=self.batches.get(self.batch_id)
        corners=np.array(self.batch['photos'][0]['placement']['corners']);centre=corners.mean(axis=0)
        self.centre=centre
        coords=[list(FROM_MAP.transform(*(centre+[x,y]))) for x,y in [(-35,35),(35,35),(35,-35),(5,-35),(5,-10),(-35,-10)]]
        self.parcel=self.store.save_parcel({'type':'Polygon','coordinates':[coords+[coords[0]]]},'Concave field')

    @staticmethod
    def cow_photo():
        image=Image.open(io.BytesIO(drone()));exif=image.getexif()
        info=PngImagePlugin.PngInfo();info.add_text('XMP',image.info['XMP'])
        ImageDraw.Draw(image).ellipse((232,172,248,188),fill=(240,236,221))
        output=io.BytesIO();image.save(output,'PNG',exif=exif,pnginfo=info)
        return output.getvalue()

    def tearDown(self):self.tmp.cleanup()

    def create(self):return self.worlds.create(self.batch_id,self.parcel['id'])

    def freeze_inputs(self, job, boxes=None):
        folder=self.worlds.root/job['id'];request=json.loads((folder/'request.json').read_text())
        photo=request['batch']['photos'][0];model=request['model'];image_hash=photo['meta']['byte_sha256']
        predictions=folder/'predictions';predictions.mkdir()
        payload={'image_sha256':image_hash,'model_sha256':model['checkpoint_sha256'],
                 'modes':{model['mode']:{'boxes':boxes if boxes is not None else [[.47,.46,.53,.54,.9],[.01,.01,.02,.02,.9]]}}}
        write(predictions/(image_hash+'.json'),payload)
        write(folder/'predictions.lock.json',{'model':model,'files':{image_hash+'.json':sha(predictions/(image_hash+'.json'))}})
        xx,yy=self.centre;transform=from_origin(xx-60.5,yy+60.5,1,1)
        values=np.broadcast_to((200+np.arange(121)*.01).astype('float32'),(121,121)).copy()
        with rasterio.open(folder/'terrain.tif','w',driver='GTiff',width=121,height=121,count=1,dtype='float32',crs='EPSG:2154',transform=transform) as ds:ds.write(values,1)
        (folder/'ign-source.tif').write_bytes((folder/'terrain.tif').read_bytes())
        write(folder/'terrain-source.json',{'sha256':sha(folder/'terrain.tif'),'vertical_reference':'synthetic test elevation'})
        return folder

    def test_duplicate_job_retry_and_immutable_boundary_snapshot(self):
        first=self.create();self.assertEqual(first['id'],self.create()['id'])
        saved=json.loads((self.worlds.root/first['id']/'request.json').read_text())
        self.assertEqual(saved['parcel'],self.parcel)
        self.assertEqual(Worlds(Store(self.root),self.batches,start_worker=False).get(first['id'])['status'],'queued')
        with self.store.connect() as db:db.execute("UPDATE world_jobs SET status='failed' WHERE id=?",(first['id'],))
        self.assertEqual(self.worlds.retry(first['id'])['status'],'queued')
        self.assertEqual(json.loads((self.worlds.root/first['id']/'request.json').read_text()),saved)

    def test_unsupported_metadata_and_nonoverlapping_boundary_are_rejected(self):
        bad=self.batches.create();self.batches.add(bad['id'],drone(gps=False),'bad.png');self.batches.build(bad['id'])
        while self.batches.get(bad['id'])['status']=='building':time.sleep(.01)
        with self.assertRaisesRegex(ValueError,'Every photo'):self.worlds.create(bad['id'],self.parcel['id'])
        coords=[list(FROM_MAP.transform(*(self.centre+[x+1000,y]))) for x,y in [(-30,30),(30,30),(30,-30),(-30,-30)]]
        outside=self.store.save_parcel({'type':'Polygon','coordinates':[coords+[coords[0]]]},'Outside')
        with self.assertRaisesRegex(ValueError,'overlap'):self.worlds.create(self.batch_id,outside['id'])

    def test_offline_replay_requires_real_saved_outputs_and_detects_tampering(self):
        folder=self.worlds.root/self.create()['id']
        with self.assertRaisesRegex(ValueError,'saved predictions'):run(folder,offline=True)
        self.freeze_inputs(self.worlds.get(folder.name))
        photo=next((folder/'inputs').iterdir());photo.write_bytes(photo.read_bytes()+b'changed')
        with self.assertRaisesRegex(ValueError,'photograph changed'):run(folder,offline=True)

    def test_polygon_clipping_original_crops_and_byte_identical_replay(self):
        folder=self.freeze_inputs(self.create())
        result=run(folder,offline=True);self.assertEqual(result['cows'],1);self.assertEqual(result['outside_boundary'],1)
        first=json.loads((folder/'build/build-manifest.json').read_text())
        second=folder/'second';run(folder,offline=True,output=second)
        self.assertEqual(first,json.loads((second/'build-manifest.json').read_text()))
        scene=json.loads((second/'scene.json').read_text());spec=scene['terrain'];valid=np.fromfile(second/'valid.bin',dtype='u1').reshape(spec['height'],spec['width'])
        # The concave cut-out is invalid, although it is inside the bounding box.
        ix=round((-20-spec['minX']));iz=round((25-spec['minZ']))
        # Scene origin is polygon centroid, so use absolute map coordinates.
        x=self.centre[0]-20-scene['origin']['easting'];z=scene['origin']['northing']-(self.centre[1]-25)
        self.assertEqual(valid[round(z-spec['minZ']),round(x-spec['minX'])],0)
        self.assertTrue(verify(second)['source_crops_exact'])
        (second/'cows'/f"{scene['cows'][0]['id']}.png").write_bytes(b'bad')
        with self.assertRaisesRegex(ValueError,'Corrupted'):verify(second)

    def test_empty_field_still_builds_a_walkable_terrain(self):
        folder=self.freeze_inputs(self.create(),boxes=[]);result=run(folder,offline=True)
        self.assertEqual(result['cows'],0);self.assertTrue(result['verification']['passed'])
        self.assertGreater(np.fromfile(folder/'build/valid.bin',dtype='u1').sum(),100)

    def test_projection_has_metric_scale_and_correct_north_orientation(self):
        photo=self.batch['photos'][0];H=matrix(photo,480,360,self.centre)
        pts=project([[0,0],[480,360]],H)
        self.assertGreater(pts[0][1],pts[1][1]);self.assertLess(pts[0][0],pts[1][0])
        np.testing.assert_allclose(pts+ self.centre, np.array(photo['placement']['corners'])[[0,2]],atol=1e-4)

    def test_overlap_merge_requires_checked_link_and_preserves_sources(self):
        def row(ident,photo,x=0):return {'id':ident,'photo_id':photo,'confidence':.9,'map_box':[[x,0],[x+2,0],[x+2,1],[x,1]],
             'map_point':[x+1,.5],'source_image':photo+'.jpg','source_crop':ident+'.png','quality_flags':[],'status':'proposed'}
        batch={'photos':[{'id':'a','meta':{'captured_local':'2023-09-26T12:00:00'}},{'id':'b','meta':{'captured_local':'2023-09-26T12:00:05'}}], 'result':{'links':[]}}
        self.assertEqual(len(merge_observations([row('1','a'),row('2','b')],batch)),2)
        batch['result']['links']=[{'photo_id':'a','reference_id':'b'}]
        rows=[row('1','a'),row('2','b',.1)]
        kept=merge_observations(rows,batch);self.assertEqual(len(kept),1);self.assertEqual(len(kept[0]['sightings']),2)
        self.assertEqual(rows[1]['status'],'merged')
        self.assertIn('cross_photo_match_needs_review',kept[0]['quality_flags'])

    def test_failed_coats_and_overlapping_models_remain_review_findings(self):
        def row(ident,x,flags):return {'id':ident,'confidence':.9,'position':[x,0,0], 'yaw':0,'quality_flags':flags,'status':'proposed'}
        rows=[row('a',0,[]),row('b',.1,[]),row('c',5,['insufficient_foreground'])]
        kept=renderable_observations(rows)
        self.assertEqual([r['id'] for r in kept],['a'])
        self.assertEqual(rows[1]['status'],'placement_review');self.assertEqual(rows[1]['conflicts_with'],'a')
        self.assertEqual(rows[2]['status'],'appearance_review')

    def test_interrupted_jobs_resume_and_failed_jobs_can_retry(self):
        import threading
        from types import SimpleNamespace
        job=self.create();folder=self.worlds.root/job['id']
        with self.store.connect() as db:db.execute("UPDATE world_jobs SET status='processing' WHERE id=?",(job['id'],))
        def execute(*args,**kwargs):
            write(folder/'result.json',{'name':'Recovered test job'})
            return SimpleNamespace(returncode=0)
        with patch('survey.worlds.subprocess.run',execute):
            worker=threading.Thread(target=self.worlds._worker);worker.start()
            deadline=time.monotonic()+5
            while self.worlds.get(job['id'])['status']!='ready' and time.monotonic()<deadline:time.sleep(.01)
            self.worlds.stopping.set();self.worlds.wake.set();worker.join(2)
        self.assertFalse(worker.is_alive());self.assertEqual(self.worlds.get(job['id'])['result']['name'],'Recovered test job')


if __name__=='__main__':unittest.main()

class WorldHTTPTests(unittest.TestCase):
    from test_survey import HTTPTests as Base
    request=Base.request

    def setUp(self):
        self.worker_patch=patch('survey.worlds.Worlds._worker');self.worker_patch.start()
        self.Base.setUp(self)

    def tearDown(self):
        self.Base.tearDown(self);self.worker_patch.stop()

    def test_world_routes_enforce_authorization_and_durable_queue(self):
        import base64
        from test_survey import polygon
        _,batch=self.request('POST','/api/survey/batches',{})
        _,added=self.request('POST',f"/api/survey/batches/{batch['id']}/photos",{'filename':'flight.png','file_base64':base64.b64encode(drone()).decode()})
        self.request('POST',f"/api/survey/batches/{batch['id']}/build",{})
        for _ in range(100):
            _,value=self.request('GET',f"/api/survey/batches/{batch['id']}")
            if value['status']=='ready':break
            time.sleep(.01)
        corners=value['photos'][0]['placement']['corners'];coords=[list(FROM_MAP.transform(*p)) for p in corners]
        _,parcel=self.request('POST','/api/survey/parcels',{'name':'HTTP world','geometry':{'type':'Polygon','coordinates':[coords+[coords[0]]]}})
        body={'batch_id':batch['id'],'parcel_id':parcel['id']}
        self.assertEqual(self.request('POST','/api/survey/worlds',body,{'X-Demo-Token':'bad'})[0],403)
        code,job=self.request('POST','/api/survey/worlds',body);self.assertEqual(code,202)
        self.assertEqual(job['status'],'queued');self.assertIsNone(job['url'])
        self.assertEqual(self.request('POST','/api/survey/worlds',body)[1]['id'],job['id'])
        _,boot=self.request('GET','/api/survey/bootstrap');self.assertEqual(boot['worlds'][0]['id'],job['id'])
        for name in ('','request.json','inputs.lock.json','../../evidence.sqlite3','%2e%2e/request.json'):
            self.assertEqual(self.request('GET',f"/worlds/{job['id']}/{name}")[0],404)
        self.assertEqual(self.request('POST',f"/api/survey/worlds/{job['id']}/retry",{}, {'Origin':'https://evil.example'})[0],403)
