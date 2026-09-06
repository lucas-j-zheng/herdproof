'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { detectTiled, type Box, type DetectConfig } from '@/lib/detect';

const MODEL_URL = '/demo/model/herdproof-yolov8n-v2.onnx';
const MAX_TILES = 80;

type Phase = 'idle' | 'loading-model' | 'running' | 'done' | 'error';

type Session = {
  run: (input: Float32Array) => Promise<{ data: Float32Array; dims: readonly number[] }>;
  backend: string;
};

export function BrowserDetector({ config }: { config: DetectConfig }) {
  const [phase, setPhase] = useState<Phase>('idle');
  const [message, setMessage] = useState('');
  const [progress, setProgress] = useState({ done: 0, total: 0 });
  const [boxes, setBoxes] = useState<Box[]>([]);
  const [confidence, setConfidence] = useState(0.7);
  const [preview, setPreview] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [backend, setBackend] = useState('');
  const session = useRef<Session | null>(null);
  const previewRef = useRef<string | null>(null);

  useEffect(() => () => { if (previewRef.current) URL.revokeObjectURL(previewRef.current); }, []);

  const ensureSession = useCallback(async (): Promise<Session> => {
    if (session.current) return session.current;
    setPhase('loading-model');
    setMessage('Downloading the 12 MB model…');
    const ort = await import('onnxruntime-web/webgpu');
    ort.env.wasm.wasmPaths = '/demo/ort/';
    ort.env.wasm.numThreads = 1; // avoids the cross-origin isolation headers threads would need

    const providers =
      typeof navigator !== 'undefined' && 'gpu' in navigator ? ['webgpu', 'wasm'] : ['wasm'];
    let inner: Awaited<ReturnType<typeof ort.InferenceSession.create>> | null = null;
    let chosen = '';
    for (const ep of providers) {
      try {
        inner = await ort.InferenceSession.create(MODEL_URL, { executionProviders: [ep] });
        chosen = ep;
        break;
      } catch {
        inner = null;
      }
    }
    if (!inner) throw new Error('No usable execution provider (tried WebGPU and WASM).');

    const name = inner.inputNames[0];
    const made: Session = {
      backend: chosen,
      run: async (input) => {
        const tensor = new ort.Tensor('float32', input, [1, 3, config.tile_size, config.tile_size]);
        const out = await inner.run({ [name]: tensor });
        const first = out[inner.outputNames[0]];
        return { data: first.data as Float32Array, dims: first.dims };
      },
    };
    session.current = made;
    setBackend(chosen);
    return made;
  }, [config.tile_size]);

  const onFile = useCallback(
    async (file: File) => {
      try {
        setBoxes([]);
        setElapsed(0);
        const url = URL.createObjectURL(file);
        if (previewRef.current) URL.revokeObjectURL(previewRef.current);
        previewRef.current = url;
        setPreview(url);

        const bitmap = await createImageBitmap(file);
        const active = await ensureSession();

        const tiles = tileCount(bitmap.width, bitmap.height, config.tile_size, config.tile_overlap);
        if (tiles > MAX_TILES) {
          bitmap.close();
          throw new Error(
            `That image needs ${tiles} tiles (limit ${MAX_TILES}). Try a photo up to about 6000×4000.`,
          );
        }

        setPhase('running');
        setMessage(
          active.backend === 'webgpu'
            ? 'Running on your GPU…'
            : 'Running on your CPU — this is the slow path.',
        );
        setProgress({ done: 0, total: tiles });

        const began = performance.now();
        const result = await detectTiled(
          bitmap,
          bitmap.width,
          bitmap.height,
          config,
          active.run,
          setProgress,
        );
        bitmap.close();

        setElapsed((performance.now() - began) / 1000);
        setBoxes(result.boxes);
        setPhase('done');
        setMessage('');
      } catch (e) {
        setPhase('error');
        setMessage(e instanceof Error ? e.message : String(e));
      }
    },
    [config, ensureSession],
  );

  const visible = boxes.filter((b) => b[4] >= confidence);
  const busy = phase === 'loading-model' || phase === 'running';

  return (
    <div className="detector">
      <div className="detector-controls">
        <label className={busy ? 'button button-yellow is-busy' : 'button button-yellow'}>
          {busy ? 'Working…' : 'Choose a photo'}
          <span aria-hidden="true">↗</span>
          <input
            type="file"
            accept="image/jpeg,image/png,image/webp"
            disabled={busy}
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) void onFile(file);
              e.target.value = '';
            }}
          />
        </label>
        <p className="detector-privacy">
          Your photo is read in this tab and never uploaded. There is no server behind this —
          the model runs on your machine.
        </p>
      </div>

      {phase === 'running' && (
        <div className="detector-progress">
          <div
            className="detector-bar"
            style={{ width: `${progress.total ? (progress.done / progress.total) * 100 : 0}%` }}
          />
          <span>
            tile {progress.done} / {progress.total} · {message}
          </span>
        </div>
      )}
      {phase === 'loading-model' && <p className="demo-status">{message}</p>}
      {phase === 'error' && <p className="demo-error">{message}</p>}

      {preview && (
        <div className="explorer-figure detector-figure">
          <img src={preview} alt="The photograph you selected, with any cattle the model proposed." />
          {phase === 'done' && (
            <svg className="explorer-overlay" viewBox="0 0 1000 1000" preserveAspectRatio="none" aria-hidden="true">
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
          )}
        </div>
      )}

      {phase === 'done' && (
        <div className="detector-result">
          <div className="explorer-count">
            <strong>{visible.length}</strong>
            <span>cattle candidates at<br />confidence ≥ {confidence.toFixed(2)}</span>
          </div>
          <label className="explorer-slider">
            <span>
              Confidence threshold<em>{confidence.toFixed(2)}</em>
            </span>
            <input
              type="range"
              min={0.1}
              max={0.95}
              step={0.01}
              value={confidence}
              onChange={(e) => setConfidence(Number(e.target.value))}
            />
          </label>
          <p className="detector-meta">
            {progress.total} tiles · {elapsed.toFixed(1)}s · {backend === 'webgpu' ? 'WebGPU' : 'WASM (CPU)'}
          </p>
        </div>
      )}

      <p className="detector-caveat">
        <strong>Expect it to do badly on most photos.</strong> This model was fine-tuned on
        nadir drone imagery of grazing cattle at survey altitude. A ground-level photo, a
        different animal, or a different camera angle is outside everything it was trained on,
        and the result you get will say more about that gap than about the model&apos;s measured
        accuracy.
      </p>
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
