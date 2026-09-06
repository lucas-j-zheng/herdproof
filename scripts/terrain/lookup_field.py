from pathlib import Path
import json
import urllib.request
import urllib.parse
from PIL import Image
from pyproj import Transformer

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'validation/terrain-demo/data/ign'
OUT.mkdir(parents=True, exist_ok=True)
with Image.open(ROOT/'validation/data/46472379c810.jpg') as image:
    gps = image.getexif().get_ifd(34853)
    def degrees(k): return sum(float(v)/d for v,d in zip(gps[k], (1,60,3600)))
    lon,lat = degrees(4),degrees(2)
east,north=Transformer.from_crs(4326,2154,always_xy=True).transform(lon,lat)
bounds=[east-250,north-250,east+250,north+250]
params=dict(SERVICE='WFS',VERSION='2.0.0',REQUEST='GetFeature',
            TYPENAMES='IGNF_MNT-LIDAR-HD:dalle',
            BBOX=','.join(map(str,bounds))+',EPSG:2154',
            OUTPUTFORMAT='application/json',COUNT=20,SRSNAME='EPSG:2154')
url='https://data.geopf.fr/wfs/ows?'+urllib.parse.urlencode(params)
with urllib.request.urlopen(url,timeout=60) as response:
    data=json.load(response)
(OUT/'tile-lookup.json').write_text(json.dumps(data,indent=2)+'\n')
print(json.dumps({'features':[f['properties'] for f in data.get('features',[])]},indent=2))
(OUT/'origin.json').write_text(json.dumps({'longitude':lon,'latitude':lat,
    'easting':east,'northing':north,'lookup_crs':'EPSG:2154',
    'query_bounds':bounds},indent=2)+'\n')
