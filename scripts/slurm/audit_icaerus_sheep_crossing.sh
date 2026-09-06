#!/usr/bin/env bash
#SBATCH --partition=batch
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:30:00
#SBATCH --job-name=herdproof-sheep-audit
#SBATCH --output=/oscar/scratch/lzheng35/herdproof/logs/audit-sheep-cross-%j.out

set -euo pipefail
module load ffmpeg/7.1-7dmq
ROOT=/oscar/scratch/lzheng35/herdproof
DATA="$ROOT/data/icaerus-sheep-crossing"
REPORT="$ROOT/audits/icaerus-sheep-crossing.json"
SAMPLES="$ROOT/audits/icaerus-sheep-crossing-samples"
rm -rf "$SAMPLES"
mkdir -p "$SAMPLES"

python3 - "$DATA" "$REPORT" "$SAMPLES" <<'PY'
from __future__ import annotations
import hashlib, json, pathlib, stat, subprocess, sys, zipfile
from collections import Counter
from pathlib import PurePosixPath
root = pathlib.Path(sys.argv[1]).resolve()
samples = pathlib.Path(sys.argv[3]).resolve()
files = sorted(path for path in root.rglob('*') if path.is_file() and path.name != '.safe-extraction.json')
videos = [path for path in files if path.suffix.lower() in {'.mp4', '.avi', '.mov', '.mkv'}]
archives = [path for path in files if path.suffix.lower() == '.zip']
video_results = []
for index, path in enumerate(videos):
    probe = json.loads(subprocess.check_output([
        'ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(path)
    ]))
    subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-f', 'null', '-'], check=True)
    stream = next(item for item in probe['streams'] if item.get('codec_type') == 'video')
    duration = float(probe.get('format', {}).get('duration', 0))
    frame_paths = []
    for sample_index, fraction in enumerate((0.15, 0.50, 0.85)):
        frame = samples / f'{index:02d}-{sample_index}-{path.stem}.jpg'
        subprocess.run([
            'ffmpeg', '-v', 'error', '-ss', str(duration * fraction), '-i', str(path),
            '-frames:v', '1', '-q:v', '2', str(frame)
        ], check=True)
        frame_paths.append(frame.name)
    video_results.append({
        'path': str(path.relative_to(root)), 'bytes': path.stat().st_size,
        'codec': stream.get('codec_name'), 'width': stream.get('width'),
        'height': stream.get('height'), 'frame_rate': stream.get('avg_frame_rate'),
        'frames': stream.get('nb_frames'), 'duration': probe.get('format', {}).get('duration'),
        'sample_frames': frame_paths,
    })
archive_results = []
for path in archives:
    with zipfile.ZipFile(path) as source:
        members = source.infolist()
        extensions = Counter()
        for member in members:
            name = PurePosixPath(member.filename)
            mode = member.external_attr >> 16
            if name.is_absolute() or '..' in name.parts or stat.S_ISLNK(mode) or member.flag_bits & 1:
                raise ValueError(f'unsafe nested ZIP member: {path}: {member.filename}')
            if not member.is_dir(): extensions[name.suffix.lower() or '<none>'] += 1
        archive_results.append({
            'path': str(path.relative_to(root)), 'bytes': path.stat().st_size,
            'members': len(members), 'uncompressed_bytes': sum(x.file_size for x in members),
            'extensions': dict(sorted(extensions.items())),
            'first_members': [x.filename for x in members[:20]],
        })
report = {
    'files': len(files),
    'extensions': dict(sorted(Counter(path.suffix.lower() or '<none>' for path in files).items())),
    'paths': [str(path.relative_to(root)) for path in files],
    'videos': video_results, 'nested_archives': archive_results,
    'all_videos_decoded': True,
}
pathlib.Path(sys.argv[2]).write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
print(json.dumps(report, indent=2, sort_keys=True))
PY

tar -C "$ROOT/audits" -cf "$ROOT/audits/icaerus-sheep-crossing-samples.tar" \
  icaerus-sheep-crossing.json icaerus-sheep-crossing-samples
