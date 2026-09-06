"""Acquire just the selected public flight, retaining checksummed originals."""
from pathlib import Path
import hashlib
import json
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from fetch_aerial_subset import RemoteReader, URL, SIZE

OUT = ROOT / 'validation/terrain-demo/data/flight'
OUT.mkdir(parents=True, exist_ok=True)
manifest_path=ROOT/'validation/data/manifest.json'
manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {'records':[], 'attribution':"Louise Helary and Adrien Lebreton / Institut de l'Elevage, ICAERUS grazing cows v2, CC BY 4.0"}
local = {Path(r['source']).name: r for r in manifest['records']
         if r['flight'] == 'Jalogny/DJI_202309261339_058'}
reader = RemoteReader(ROOT / 'validation/data/ranges')
with zipfile.ZipFile(reader) as archive:
    infos = [i for i in archive.infolist()
             if '/JPGImages/DJI_202309261339_058/' in i.filename
             and i.filename.lower().endswith('.jpg')]
rows = []
for index, info in enumerate(infos):
    name = Path(info.filename).name
    path = OUT / name
    if not path.exists():
        if name in local and (ROOT / 'validation/data' / local[name]['image']).exists():
            shutil.copyfile(ROOT / 'validation/data' / local[name]['image'], path)
        else:
            raw = reader.member(info)
            temporary = path.with_suffix('.download')
            temporary.write_bytes(raw)
            temporary.replace(path)
    import zlib
    raw = path.read_bytes()
    if len(raw) != info.file_size or zlib.crc32(raw) & 0xffffffff != info.CRC:
        raise RuntimeError('Size or CRC mismatch: ' + name)
    rows.append({'name': name, 'archive_member': info.filename,
                 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
                 'crc32': f'{info.CRC:08x}', 'verified_crc32': True})
    (OUT / 'manifest.json').write_text(json.dumps({
        'source_url': URL, 'archive_bytes': SIZE,
        'integrity': 'Per-member ZIP CRC32 and local SHA256; whole-archive hash not verified.',
        'attribution': manifest['attribution'], 'expected_images': len(infos),
        'complete': len(rows) == len(infos), 'images': rows}, indent=2) + '\n')
    print(f'{index + 1}/{len(infos)} {name} verified', flush=True)
