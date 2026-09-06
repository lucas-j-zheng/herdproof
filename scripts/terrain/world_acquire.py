"""Explicit IGN acquisition; never called by offline prepare/build."""
import argparse
import urllib.parse
import urllib.request
from pathlib import Path

import rasterio

from world_core import read,sha,write


def main():
    p=argparse.ArgumentParser();p.add_argument('--easting',type=float,required=True);p.add_argument('--northing',type=float,required=True)
    p.add_argument('--size',type=float,default=300);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=True)
    # Pixel centres include an exact 0.5m-spaced sample at the declared origin.
    bounds=[a.easting-a.size/2-.25,a.northing-a.size/2+.25,a.easting+a.size/2-.25,a.northing+a.size/2+.25]
    jobs=[('terrain.tif','IGNF_LIDAR-HD_MNT_ELEVATION.ELEVATIONGRIDCOVERAGE.LAMB93','image/geotiff',round(a.size/.5)),
          ('reference.jpg','ORTHOIMAGERY.ORTHOPHOTOS','image/jpeg',round(a.size/.2))]
    sources=[]
    for name,layer,fmt,size in jobs:
        params=dict(SERVICE='WMS',VERSION='1.3.0',REQUEST='GetMap',STYLES='',CRS='EPSG:2154',BBOX=','.join(map(str,bounds)),WIDTH=size,HEIGHT=size,LAYERS=layer,FORMAT=fmt)
        url='https://data.geopf.fr/wms-r?'+urllib.parse.urlencode(params);file=a.output/name
        if not file.exists():
            with urllib.request.urlopen(url,timeout=60) as response:data=response.read()
            if data.lstrip().startswith(b'<'):raise ValueError(data[:500].decode())
            tmp=file.with_suffix('.download');tmp.write_bytes(data);tmp.replace(file)
        sources.append({'file':name,'sha256':sha(file),'url':url,'bounds_lambert93':bounds,'width':size,'height':size,
                        'provider':'IGN','license':'Licence Ouverte 2.0'})
        print(name,file.stat().st_size,flush=True)
    with rasterio.open(a.output/'terrain.tif') as ds:
        heights=ds.read(1,masked=True)
        if heights.dtype.kind!='f':raise ValueError('Expected numeric terrain heights')
        sources[0].update(valid_fraction=float(heights.count()/heights.size),min_m=float(heights.min()),max_m=float(heights.max()),transform=list(ds.transform))
    write(a.output/'source-manifest.json',{'sources':sources,'vertical_reference':'IGN LAMB93 NGF-IGN69 product; acquisition epoch unresolved',
                                         'note':'Reference orthophoto may have a different date from the drone image.'})


if __name__=='__main__':main()
