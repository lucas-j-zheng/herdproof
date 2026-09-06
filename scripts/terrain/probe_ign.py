"""User-authorized IGN elevation query for the original demo photo GPS."""
from pathlib import Path
import json
import sys
import urllib.request
import urllib.parse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from aerial_survey import metadata

out = ROOT / 'validation/terrain-demo/data/ign'
out.mkdir(parents=True, exist_ok=True)
meta = metadata(ROOT / 'validation/data/46472379c810.jpg')
for resource in ['ign_lidar_hd_mnt_mono_wld', 'ign_rge_alti_par_territoires']:
    payload = dict(lon=str(meta['lon']), lat=str(meta['lat']), resource=resource,
                   measures='true', zonly='false')
    url = 'https://data.geopf.fr/altimetrie/1.0/calcul/alti/rest/elevation.json'
    request = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                     headers={'Content-Type': 'application/json',
                                              'User-Agent': 'HerdProofTerrain/0.1'})
    with urllib.request.urlopen(request, timeout=45) as response:
        result = json.load(response)
    (out / f'probe-{resource}.json').write_text(json.dumps(result, indent=2)+'\n')
    print(resource, json.dumps(result), flush=True)
