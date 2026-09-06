'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import type { Box } from '@/lib/detect';

type Photo = {
  id: string;
  width: number;
  height: number;
  display: [number, number];
  boxes: Box[];
  at70: number;
};

type Manifest = {
  model_id: string;
  default_confidence: number;
  confidence_floor: number;
  tile_size: number;
  tile_overlap: number;
  global_nms_iou: number;
  photos: Photo[];
};

export function DetectionExplorer() {
  const [manifest, setManifest] = useState<Manifest | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [active, setActive] = useState(0);
  const [confidence, setConfidence] = useState(0.7);
  const figure = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    fetch('/demo/detections.json')
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((m: Manifest) => {
        if (cancelled) return;
        setManifest(m);
        setConfidence(m.default_confidence);
      })
      .catch((e) => !cancelled && setError(String(e.message ?? e)));
    return () => { cancelled = true; };
  }, []);

  const photo = manifest?.photos[active];
  const visible = useMemo(
    () => (photo ? photo.boxes.filter((b) => b[4] >= confidence) : []),
    [photo, confidence],
  );

  if (error) {
    return <p className="demo-error">The saved detections could not be loaded ({error}).</p>;
  }
  if (!manifest || !photo) {
    return <p className="demo-status">Loading saved detections…</p>;
  }

  const floor = manifest.confidence_floor;
  const tiles = tileCount(photo.width, photo.height, manifest.tile_size, manifest.tile_overlap);

  return (
    <div className="explorer">
      <div className="explorer-stage">
        <div className="explorer-figure" ref={figure}>
          <img
            src={`/demo/photos/${photo.id}.jpg`}
            width={photo.display[0]}
            height={photo.display[1]}
            alt={`Aerial survey photograph ${photo.id}, shown with the cattle detections the model proposed at or above ${confidence.toFixed(2)} confidence.`}
            loading="lazy"
          />
          <svg
            className="explorer-overlay"
            viewBox="0 0 1000 1000"
            preserveAspectRatio="none"
            aria-hidden="true"
          >
            {visible.map((b, i) => (
              <rect
                key={i}
                x={b[0] * 1000}
                y={b[1] * 1000}
                width={Math.max(0.0015, b[2] - b[0]) * 1000}
                height={Math.max(0.0015, b[3] - b[1]) * 1000}
                vectorEffect="non-scaling-stroke"
                className={b[4] >= 0.7 ? 'box-strong' : 'box-weak'}
              />
            ))}
          </svg>
          <div className="explorer-topline">
            <span>{photo.id}</span>
            <span>{photo.width}×{photo.height} · {tiles} TILES</span>
          </div>
        </div>

        <div className="explorer-readout">
          <div className="explorer-count">
            <strong>{visible.length}</strong>
            <span>
              cattle candidates at<br />confidence ≥ {confidence.toFixed(2)}
            </span>
          </div>
          <label className="explorer-slider">
            <span>
              Confidence threshold
              <em>{confidence.toFixed(2)}</em>
            </span>
            <input
              type="range"
              min={floor}
              max={0.95}
              step={0.01}
              value={confidence}
              onChange={(e) => setConfidence(Number(e.target.value))}
            />
            <span className="explorer-scale" aria-hidden="true">
              <em>{floor.toFixed(2)}</em>
              <em>0.95</em>
            </span>
          </label>
          <button
            type="button"
            className="explorer-reset"
            onClick={() => setConfidence(manifest.default_confidence)}
            disabled={confidence === manifest.default_confidence}
          >
            Reset to the operating point ({manifest.default_confidence.toFixed(2)})
          </button>
          <p className="explorer-note">
            Every box below was produced by the model, not by a person. Lower the threshold
            and uncertain candidates appear; raise it and real animals start dropping out.
            That trade is the reason a count needs a reviewer.
          </p>
        </div>
      </div>

      <div className="explorer-picker" role="tablist" aria-label="Survey photographs">
        {manifest.photos.map((p, i) => (
          <button
            key={p.id}
            type="button"
            role="tab"
            aria-selected={i === active}
            className={i === active ? 'thumb thumb-active' : 'thumb'}
            onClick={() => setActive(i)}
          >
            <img src={`/demo/photos/${p.id}.jpg`} alt="" loading="lazy" width={160} height={120} />
            <span>{p.at70} at 0.70</span>
          </button>
        ))}
      </div>
    </div>
  );
}

function tileCount(width: number, height: number, size: number, overlap: number) {
  const axis = (length: number) => {
    if (length <= size) return 1;
    const step = Math.max(1, Math.trunc(size * (1 - overlap)));
    const set = new Set<number>();
    for (let v = 0; v <= length - size; v += step) set.add(v);
    set.add(length - size);
    return set.size;
  };
  return axis(width) * axis(height);
}
