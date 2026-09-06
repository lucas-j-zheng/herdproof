"""Verify a private world archive and reproduce all outputs in a fresh extraction."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('archive',type=Path);p.add_argument('--report',type=Path,required=True);a=p.parse_args()
    extracted=Path(tempfile.mkdtemp(prefix='herdproof-upload-replay-')).resolve()
    with zipfile.ZipFile(a.archive) as archive:
        manifest=json.loads(archive.read('bundle-manifest.json'))['files']
        names=archive.namelist()
        assert len(names)==len(set(names)), 'Duplicate archive entries'
        assert set(names)==set(manifest)|{'bundle-manifest.json'}, 'Archive membership differs'
        for name,digest in manifest.items():
            assert (extracted/name).resolve().is_relative_to(extracted), 'Unsafe archive path'
            assert hashlib.sha256(archive.read(name)).hexdigest()==digest, 'Archive hash mismatch: '+name
        archive.extractall(extracted)
    job=next((extracted/'validation/survey-export').iterdir())
    log=a.report.with_suffix('.log')
    with log.open('w') as out:
        subprocess.run([sys.executable,str(extracted/'scripts/survey/world_pipeline.py'),'--job',str(job),'--offline'],cwd=extracted,stdout=out,stderr=subprocess.STDOUT,check=True,timeout=600)
    expected=json.loads((job/'expected-build-manifest.json').read_text());actual=json.loads((job/'build/build-manifest.json').read_text())
    assert actual==expected, 'Replayed output manifest differs'
    result={'passed':True,'archive_sha256':sha(a.archive),'archive_members_verified':len(manifest),
            'extracted_root':str(extracted),'scene_id':job.name,'output_files_identical':len(actual['output_sha256']),
            'complete_manifest_identical':True,'offline_replay':True,
            'runtime_note':'Used the prepared locked terrain interpreter; source, inputs, assets and browser libraries came from the fresh extraction.'}
    a.report.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))


if __name__=='__main__':main()
