"""Retrieve numeric IGN terrain and a map reference with explicit georeferencing."""
from pathlib import Path
import json
import urllib.request
import urllib.parse
import hashlib
import time
import rasterio
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'validation/terrain-demo/data/ign'
origin=json.loads((OUT/'origin.json').read_text())
e,n=round(origin['easting']),round(origin['northing'])
bound=[e-250-.25,n-250+.25,e+250-.25,n+250+.25]
base=dict(SERVICE='WMS',VERSION='1.3.0',REQUEST='GetMap',STYLES='',
          CRS='EPSG:2154',BBOX=','.join(map(str,bound)),WIDTH=1000,HEIGHT=1000)
jobs=[('terrain.tif',dict(base,LAYERS='IGNF_LIDAR-HD_MNT_ELEVATION.ELEVATIONGRIDCOVERAGE.LAMB93',FORMAT='image/geotiff')),
      ('reference-ortho.jpg',dict(base,LAYERS='ORTHOIMAGERY.ORTHOPHOTOS',FORMAT='image/jpeg',WIDTH=2500,HEIGHT=2500))]
sources=[]
for name,params in jobs:
    path=OUT/name
    url='https://data.geopf.fr/wms-r?'+urllib.parse.urlencode(params)
    if not path.exists():
        with urllib.request.urlopen(url,timeout=90) as response: raw=response.read()
        if raw.lstrip().startswith(b'<'):raise RuntimeError(raw[:2000].decode())
        tmp=path.with_suffix('.download');tmp.write_bytes(raw);tmp.replace(path)
    sources.append({'file':name,'url':url,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                    'bounds_lambert93':bound,'width':params['WIDTH'],'height':params['HEIGHT'],
                    'retrieved':'2026-09-06','provider':'IGN','license':'Licence Ouverte 2.0'})
    print('Retrieved',name,path.stat().st_size,flush=True)
with rasterio.open(OUT/'terrain.tif') as ds:
    z=ds.read(1,masked=True)
    sources[0].update(crs=ds.crs.to_wkt(),transform=list(ds.transform),nodata=ds.nodata,
                      dtype=str(z.dtype),min_m=float(z.min()),max_m=float(z.max()),
                      valid_fraction=float(np.count_nonzero(~np.ma.getmaskarray(z))/z.size))
    print(json.dumps({k:sources[0][k] for k in ['dtype','min_m','max_m','valid_fraction']},indent=2))
    if z.dtype.kind != 'f':raise RuntimeError('Expected numeric floating point heights')
(OUT/'source-manifest.json').write_text(json.dumps({'sources':sources,
    'vertical_reference':'NGF-IGN69 according to IGN LAMB93 product naming; validate acquisition metadata',
    'note':'Source raster subset via IGN numeric GeoTIFF WMS. Ortho is map-reference imagery of potentially different date.'},indent=2)+'\n')
