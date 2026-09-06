"""Contract tests for reproducible identities, review, appearance and geometry."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image,ImageOps
from rasterio.transform import from_origin

from world_core import (appearance,default_review,detections,digest,pixel_transform,
                        prepare,read,sha,source_image,validate_review,write)
from world_geometry import Camera,Terrain
from world import prepare_field
from world_build import ROOT,build,verify


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='herdproof-world-test-')
        self.base=Path(self.temp.name)
        rgb=np.full((100,120,3),[38,119,46],np.uint8)
        import cv2
        cv2.ellipse(rgb,(38,46),(15,7),25,0,360,(231,220,190),-1)
        cv2.ellipse(rgb,(82,61),(10,6),130,0,360,(25,22,20),-1)
        Image.fromarray(rgb).save(self.base/'image.png')
        self.hash=sha(self.base/'image.png')
        self.raw={'image_sha256':self.hash,'coordinate_space':'normalized_image','model':'fixture',
                  'observations':[{'id':'cow-a','box':[.15,.25,.48,.65],'confidence':.9},
                                  {'id':'cow-b','box':[.57,.44,.81,.79],'confidence':.8}]}
        write(self.base/'detections.json',self.raw)
        heights=np.zeros((81,101),np.float32)
        with rasterio.open(self.base/'terrain.tif','w',driver='GTiff',height=81,width=101,count=1,dtype='float32',crs='EPSG:2154',transform=from_origin(-25.25,20.25,.5,.5),nodata=-9999) as ds:
            ds.write(heights,1)
        self.camera={'origin_enu':[0,0,0],'K':[[100,0,60],[0,100,50],[0,0,1]],'distortion':[0]*5,
                     'world_to_camera_R':[[1,0,0],[0,-1,0],[0,0,-1]],'camera_centre_enu':[0,0,20],
                     'source_image_sha256':self.hash,'method':'Synthetic test camera'}
        write(self.base/'camera.json',self.camera)
        self.config={'schema_version':2,'scene_id':'fixture','name':'Fixture','source_image':'image.png','detections':'detections.json',
                     'terrain':'terrain.tif','camera':'camera.json','origin_enu':[0,0,0],'horizontal_crs':'EPSG:2154','vertical_reference':'synthetic test',
                     'terrain_window':[0,0,81,101],'atlas_resolution':128,
                     'cow_model':str(ROOT/'validation/terrain-demo/assets/cow-original.glb'),
                     'cow_normal':str(ROOT/'validation/terrain-demo/assets/cow-normal.png')}
        write(self.base/'field.json',self.config)

    def tearDown(self):self.temp.cleanup()

    def test_reordered_detections_keep_snapshot_and_ids(self):
        first,_=prepare(self.base/'field.json')
        self.raw['observations'].reverse();write(self.base/'detections.json',self.raw)
        second,_=prepare(self.base/'field.json')
        self.assertEqual(first,second)
        self.assertEqual([r['id'] for r in second['observations']],['cow-a','cow-b'])

    def test_reviews_cannot_cross_snapshots(self):
        first,_=prepare(self.base/'field.json');review=default_review(first['snapshot'])
        self.raw['observations'][0]['box'][0]+=.01;write(self.base/'detections.json',self.raw)
        changed,_=prepare(self.base/'field.json')
        with self.assertRaisesRegex(ValueError,'different image/detection snapshot'):validate_review(review,changed)
        self.raw['image_sha256']='wrong';write(self.base/'detections.json',self.raw)
        with self.assertRaisesRegex(ValueError,'image hash'):prepare(self.base/'field.json')

    def test_mask_colors_do_not_average_background(self):
        rgb,_=source_image(self.base/'image.png')
        for row,expected in zip(self.raw['observations'],([231,220,190],[25,22,20])):
            proposal,_,mask=appearance(rgb,row)
            observed=[int(proposal['coat_color'][i:i+2],16) for i in (1,3,5)]
            self.assertLess(np.linalg.norm(np.array(observed)-expected),4)
            self.assertGreater(np.count_nonzero(mask),100)

    def test_input_lock_detects_changed_camera(self):
        prepare_field(self.base/'field.json')
        self.camera['camera_centre_enu'][2]=22;write(self.base/'camera.json',self.camera)
        with self.assertRaisesRegex(ValueError,'lock changed'):build(self.base/'field.json')

    def test_absolute_camera_convention_and_holes(self):
        terrain=Terrain(self.base/'terrain.tif',[0,0,81,101],[0,0,0],'EPSG:2154')
        _,meta=source_image(self.base/'image.png');cam=Camera(self.camera,terrain,meta)
        np.testing.assert_allclose(cam.hit([70,70]),[2,0,4],atol=1e-7)
        np.testing.assert_allclose(cam.project([2,0,4])[0],[70,70],atol=1e-7)
        with self.assertRaisesRegex(ValueError,'valid measured terrain|misses terrain'):cam.hit([5000,5000])
        terrain.valid[40:44,50:54]=0
        with self.assertRaisesRegex(ValueError,'missing cells'):terrain.sample(.2,.2)
        bad=copy.deepcopy(self.camera);bad['world_to_camera_R']=[[1,0,0],[0,1,0],[0,0,1]]
        with self.assertRaisesRegex(ValueError,'Skyward'):Camera(bad,terrain,meta).hit([60,50])

    def test_all_exif_pixel_transforms(self):
        array=np.arange(4*7*3,dtype=np.uint8).reshape(4,7,3)
        for orientation in range(1,9):
            im=Image.fromarray(array);exif=im.getexif();exif[274]=orientation;im.save(self.base/'oriented.png',exif=exif)
            normalized,meta=source_image(self.base/'oriented.png');matrix=np.array(meta['raw_to_normalized'])
            for x,y in ((0,0),(6,0),(0,3),(6,3),(2,1)):
                a,b,_=np.r_[x,y,1]@matrix.T
                np.testing.assert_array_equal(normalized[int(b),int(a)],array[y,x])

    def test_review_validation_merge_and_manual_ids(self):
        prepared,_=prepare(self.base/'field.json');r=default_review(prepared['snapshot'])
        r['observations']={'cow-b':{'status':'rejected','merge_into':'cow-a'}}
        validate_review(r,prepared)
        r['observations']['cow-a']={'status':'rejected'}
        with self.assertRaisesRegex(ValueError,'rejected observation'):validate_review(r,prepared)
        r=default_review(prepared['snapshot']);r['additions']=[{'id':'cow-a','box':[.1,.1,.2,.2]}]
        with self.assertRaisesRegex(ValueError,'manual observation ID'):validate_review(r,prepared)
        r=default_review(prepared['snapshot']);r['observations']={'cow-a':{'coat_color':'javascript:evil'}}
        with self.assertRaisesRegex(ValueError,'coat color'):validate_review(r,prepared)

    def test_fresh_rebuilds_and_persistent_edit_isolation(self):
        prepare_field(self.base/'field.json')
        a=build(self.base/'field.json',self.base/'first');b=build(self.base/'field.json',self.base/'second')
        self.assertEqual(read(a/'build-manifest.json'),read(b/'build-manifest.json'))
        before=read(a/'scene.json');review=read(self.base/'review.json')
        review['observations']['cow-a']={'status':'accepted','coat_color':'#844421','axis_degrees':245,'head_status':'reviewed'}
        write(self.base/'review.json',review)
        c=build(self.base/'field.json',self.base/'edited');after=read(c/'scene.json')
        self.assertEqual(after['cows'][0]['coat_color'],'#844421');self.assertEqual(after['cows'][0]['axis_degrees'],245)
        self.assertEqual(before['cows'][1],after['cows'][1])
        self.assertEqual(read(c/'review.json'),review)
        self.assertTrue(verify(c)['passed'])
        (c/after['cows'][0]['source_crop']).write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError,'corrupted scene output'):verify(c)

    def test_manual_addition_and_mask_correction_rebuild(self):
        prepare_field(self.base/'field.json');prepared,_=prepare(self.base/'field.json')
        review=read(self.base/'review.json');review['additions']=[{'id':'manual-c','box':[.1,.1,.18,.2]}]
        review['observations']={'cow-b':{'status':'rejected'},'manual-c':{'status':'accepted','coat_color':'#cccccc'},
                                'cow-a':{'mask_strokes':[{'points':[[36,36]],'radius':2,'foreground':True}]}}
        write(self.base/'review.json',review)
        out=build(self.base/'field.json');self.assertEqual([c['sceneCowId'] for c in read(out/'scene.json')['cows']],['cow-a','manual-c'])
        self.assertTrue(verify(out)['source_crops_exact'])

    def test_empty_scene_and_missing_inputs(self):
        self.raw['observations']=[];write(self.base/'detections.json',self.raw);prepare_field(self.base/'field.json')
        out=build(self.base/'field.json');self.assertEqual(verify(out)['cows'],0)
        (self.base/'terrain.tif').unlink()
        with self.assertRaisesRegex(ValueError,'Missing required input terrain'):build(self.base/'field.json')


if __name__=='__main__':unittest.main(verbosity=2)
