#!/usr/bin/env bash
#SBATCH --partition=batch
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=01:00:00
#SBATCH --job-name=herdproof-cows21
#SBATCH --output=/oscar/scratch/lzheng35/herdproof/logs/download-cows21-%j.out

set -euo pipefail
module load ffmpeg/7.1-7dmq

ROOT=/oscar/scratch/lzheng35/herdproof
MANIFEST="$ROOT/datasets/cows2021-video-sample.json"
DESTINATION="$ROOT/data/cows2021-video-sample"
REPORT="$ROOT/audits/cows2021-video-sample.json"
mkdir -p "$DESTINATION" "$ROOT/audits" "$ROOT/logs"

python3 - "$MANIFEST" "$DESTINATION" <<'PY'
import json, pathlib, subprocess, sys
manifest = json.load(open(sys.argv[1]))
destination = pathlib.Path(sys.argv[2])
for sample in manifest["samples"]:
    output = destination / f'{sample["sequence"]}.avi'
    temporary = output.with_suffix(".avi.part")
    if not output.exists():
        subprocess.run([
            "curl", "--proto", "=https", "--tlsv1.2", "--fail", "--location",
            "--retry", "8", "--retry-all-errors", "--connect-timeout", "30",
            "--continue-at", "-", sample["url"], "-o", str(temporary),
        ], check=True)
        temporary.replace(output)
    if output.stat().st_size != sample["bytes"]:
        raise ValueError(f"size mismatch for {output}")
PY

python3 - "$MANIFEST" "$DESTINATION" "$REPORT" <<'PY'
import hashlib, json, pathlib, subprocess, sys
manifest = json.load(open(sys.argv[1]))
destination = pathlib.Path(sys.argv[2])
results = []
for sample in manifest["samples"]:
    path = destination / f'{sample["sequence"]}.avi'
    hasher = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            hasher.update(chunk)
    digest = hasher.hexdigest()
    probe = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)
    ]))
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "null", "-"], check=True)
    video = next(stream for stream in probe["streams"] if stream.get("codec_type") == "video")
    results.append({
        "sequence": sample["sequence"], "bytes": path.stat().st_size,
        "sha256": digest, "codec": video.get("codec_name"),
        "width": video.get("width"), "height": video.get("height"),
        "frame_rate": video.get("avg_frame_rate"), "frames": video.get("nb_frames"),
        "duration": probe.get("format", {}).get("duration"),
    })
report = {"source_manifest": manifest, "videos": results, "all_decoded": True}
pathlib.Path(sys.argv[3]).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
print(json.dumps(report, indent=2, sort_keys=True))
PY
