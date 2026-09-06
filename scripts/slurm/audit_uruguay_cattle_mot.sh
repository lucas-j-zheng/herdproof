#!/usr/bin/env bash
#SBATCH --partition=batch
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:30:00
#SBATCH --job-name=herdproof-cattle-mot-audit
#SBATCH --output=/oscar/scratch/lzheng35/herdproof/logs/audit-cattle-mot-%j.out

set -euo pipefail
module load ffmpeg/7.1-7dmq
ROOT=/oscar/scratch/lzheng35/herdproof
DATA="$ROOT/data/uruguay-cattle-mot"
REPORT="$ROOT/audits/uruguay-cattle-mot.json"
SAMPLES="$ROOT/audits/uruguay-cattle-mot-samples"
rm -rf "$SAMPLES"
mkdir -p "$SAMPLES"

python3 - "$DATA" "$REPORT" "$SAMPLES" <<'PY'
from __future__ import annotations
import csv, hashlib, json, pathlib, subprocess, sys
from collections import Counter
root = pathlib.Path(sys.argv[1]).resolve()
samples = pathlib.Path(sys.argv[3]).resolve()
files = sorted(path for path in root.rglob('*') if path.is_file() and path.name != '.safe-extraction.json')
extensions = Counter(path.suffix.lower() or '<none>' for path in files)
videos = [path for path in files if path.suffix.lower() in {'.mp4', '.avi', '.mov', '.mkv'}]
text_files = [path for path in files if path.suffix.lower() in {'.csv', '.txt', '.ini'}]
results = []
for video_index, path in enumerate(videos):
    hasher = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''): hasher.update(chunk)
    probe = json.loads(subprocess.check_output([
        'ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(path)
    ]))
    subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-f', 'null', '-'], check=True)
    stream = next(item for item in probe['streams'] if item.get('codec_type') == 'video')
    duration = float(probe.get('format', {}).get('duration', 0))
    sample_path = samples / f'{video_index:02d}-{path.stem}.jpg'
    subprocess.run([
        'ffmpeg', '-v', 'error', '-ss', str(duration / 2), '-i', str(path),
        '-frames:v', '1', '-q:v', '2', str(sample_path)
    ], check=True)
    results.append({
        'path': str(path.relative_to(root)), 'bytes': path.stat().st_size,
        'sha256': hasher.hexdigest(), 'codec': stream.get('codec_name'),
        'width': stream.get('width'), 'height': stream.get('height'),
        'frame_rate': stream.get('avg_frame_rate'), 'frames': stream.get('nb_frames'),
        'duration': probe.get('format', {}).get('duration'),
        'sample_frame': sample_path.name,
    })

text_results = []
for path in text_files:
    content = path.read_text(errors='replace')
    if len(content.encode()) > 1_000_000:
        raise ValueError(f'text metadata exceeds audit limit: {path}')
    rows = list(csv.reader(content.splitlines())) if path.suffix.lower() in {'.csv', '.txt'} else []
    widths = Counter(len(row) for row in rows)
    text_results.append({
        'path': str(path.relative_to(root)), 'lines': len(content.splitlines()),
        'column_counts': dict(sorted(widths.items())), 'first_rows': rows[:5],
        'content': content if len(content) <= 20_000 else None,
    })
report = {
    'files': len(files), 'extensions': dict(sorted(extensions.items())),
    'paths': [str(path.relative_to(root)) for path in files],
    'videos': results, 'text_files': text_results, 'all_videos_decoded': True,
}
pathlib.Path(sys.argv[2]).parent.mkdir(parents=True, exist_ok=True)
pathlib.Path(sys.argv[2]).write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
print(json.dumps(report, indent=2, sort_keys=True))
PY

tar -C "$ROOT/audits" -cf "$ROOT/audits/uruguay-cattle-mot-samples.tar" \
  uruguay-cattle-mot.json uruguay-cattle-mot-samples
