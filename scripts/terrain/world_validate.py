"""Audit two real fields with fresh exports and independent raster comparisons."""
import argparse
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import numpy as np
import rasterio

from world_core import load_config,read,sha,write
from world_build import ROOT,build,verify


def main():
    p=argparse.ArgumentParser();p.add_argument('--config',required=True,action='append',type=Path)
    p.add_argument('--report',required=True,type=Path);args=p.parse_args();reports=[]
    for path in args.config:
        base,cfg=load_config(path);start=time.perf_counter()
        with tempfile.TemporaryDirectory(prefix='world-replay-') as temp:
            first=build(path,Path(temp)/'first');first_seconds=time.perf_counter()-start
            start=time.perf_counter();second=build(path,Path(temp)/'second');second_seconds=time.perf_counter()-start
            a=read(first/'build-manifest.json');b=read(second/'build-manifest.json')
            if a!=b:raise ValueError('Two clean exports differ for '+cfg['scene_id'])
            verification=verify(first)
            heights=np.fromfile(first/'heights.bin',dtype='<f4')
            valid=np.fromfile(first/'valid.bin',dtype=np.uint8)
            with rasterio.open(base/cfg['terrain']) as raster:
                r,c,h,w=cfg['terrain_window'];source=raster.read(1,window=rasterio.windows.Window(c,r,w,h),masked=True)
                expected_valid=~np.ma.getmaskarray(source)&np.isfinite(source.data)
                if not np.array_equal(valid.reshape(h,w)>0,expected_valid):raise ValueError('Terrain validity mask changed')
                max_error=float(np.max(np.abs(heights[valid>0].astype(float)+cfg['origin_enu'][2]-source.data.ravel()[valid>0])))
                if max_error>1e-5:raise ValueError('Export changed measured heights')
                s=read(first/'scene.json')['terrain']
                if abs(s['minX']-(raster.transform.c+(c+.5)*raster.res[0]-cfg['origin_enu'][0]))>1e-8:raise ValueError('Wrong pixel-centre convention')
                if abs(s['minZ']-(-(raster.transform.f-(r+.5)*raster.res[1]-cfg['origin_enu'][1])))>1e-8:raise ValueError('Wrong northing direction')
            scene=read(first/'scene.json')
            run=subprocess.run(['node',str(ROOT/'validation/world-viewer/test_world.mjs'),str(first)],capture_output=True,text=True)
            if run.returncode:raise ValueError(run.stdout+run.stderr)
            physics=json.loads(run.stdout)
            reports.append({'scene_id':cfg['scene_id'],'config':str(path),'passed':True,'clean_builds':2,
                            'byte_identical_manifest_and_outputs':True,'files_compared':len(a['output_sha256']),
                            'first_build_seconds':first_seconds,'second_build_seconds':second_seconds,
                            'geometry':verification,'raster_height_max_error_m':max_error,'physics':physics,
                            'scene_sha256':sha(first/'scene.json'),'snapshot':scene['snapshot'],
                            'reviewed_cows':sum(c['status']=='accepted' for c in scene['cows']),
                            'unknown_head_count':sum(c['head_status']=='unknown' for c in scene['cows']),
                            'appearance_flagged':sum(bool(c['quality_flags']) for c in scene['cows']),
                            'actual_colors':sorted({c['coat_color'] for c in scene['cows']}),
                            'source_sha256':a['source_sha256'],'input_sha256':a['inputs']})
        print(cfg['scene_id']+': clean replay, source crops, original elevations and collisions passed',flush=True)
    if len({r['scene_id'] for r in reports})!=len(reports):raise ValueError('Duplicate field in audit')
    if len(reports)>1 and any(r['source_sha256']!=reports[0]['source_sha256'] for r in reports[1:]):
        raise ValueError('Fields were built with different core source code')
    write(args.report,{'passed':True,'same_core_source':True,'fields':reports,
                       'scope':'Local offline repeatability and implementation geometry, not absolute survey accuracy. White-coat field examples do not establish color performance on other breeds.'})


if __name__=='__main__':main()
