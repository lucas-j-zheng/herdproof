// Browser port of training/infer.py:predict_image. Tile geometry, class filter and the
// two NMS stages are kept identical to the Python pipeline so counts stay comparable.

export type Box = [number, number, number, number, number]; // x1, y1, x2, y2, confidence

export type DetectConfig = {
  tile_size: number;
  tile_overlap: number;
  model_imgsz: number;
  tile_nms_iou: number;
  global_nms_iou: number;
  inference_confidence_floor: number;
  max_detections_per_tile: number;
};

/** training/data.py:starts */
export function starts(length: number, size: number, overlap: number): number[] {
  if (length <= size) return [0];
  const step = Math.max(1, Math.trunc(size * (1 - overlap)));
  const out = new Set<number>();
  for (let v = 0; v <= length - size; v += step) out.add(v);
  out.add(length - size);
  return [...out].sort((a, b) => a - b);
}

/** training/metrics.py:iou */
export function iou(a: Box, b: Box): number {
  const overlap =
    Math.max(0, Math.min(a[2], b[2]) - Math.max(a[0], b[0])) *
    Math.max(0, Math.min(a[3], b[3]) - Math.max(a[1], b[1]));
  const union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - overlap;
  return union > 0 ? overlap / union : 0;
}

/** Greedy NMS, matching torchvision.ops.nms ordering used by training/evaluate.py. */
export function nms(boxes: Box[], threshold: number, limit = Infinity): Box[] {
  const kept: Box[] = [];
  for (const box of [...boxes].sort((x, y) => y[4] - x[4])) {
    if (kept.length >= limit) break;
    let clear = true;
    for (const prior of kept) {
      if (iou(box, prior) > threshold) { clear = false; break; }
    }
    if (clear) kept.push(box);
  }
  return kept;
}

/** Decode one YOLOv8 ONNX head: [1, 4 + classes, anchors], xywh in input pixels. */
export function decode(data: Float32Array, dims: readonly number[], floor: number): Box[] {
  const anchors = dims[2];
  const boxes: Box[] = [];
  for (let i = 0; i < anchors; i++) {
    const score = data[4 * anchors + i];
    if (score < floor) continue;
    const cx = data[i], cy = data[anchors + i], w = data[2 * anchors + i], h = data[3 * anchors + i];
    boxes.push([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2, score]);
  }
  return boxes;
}

export type Progress = { done: number; total: number };

/**
 * Run the tiled pipeline over a full-resolution image already drawn to a canvas.
 * `run` receives one 1024x1024 RGB tile and returns the raw model output.
 */
export async function detectTiled(
  source: CanvasImageSource,
  width: number,
  height: number,
  config: DetectConfig,
  run: (input: Float32Array) => Promise<{ data: Float32Array; dims: readonly number[] }>,
  onProgress?: (p: Progress) => void,
): Promise<{ boxes: Box[]; tiles: number }> {
  const size = config.tile_size;
  const xs = starts(width, size, config.tile_overlap);
  const ys = starts(height, size, config.tile_overlap);
  const total = xs.length * ys.length;

  const tile = document.createElement('canvas');
  tile.width = size;
  tile.height = size;
  const ctx = tile.getContext('2d', { willReadFrequently: true });
  if (!ctx) throw new Error('Canvas 2D is unavailable in this browser.');

  const input = new Float32Array(3 * size * size);
  const plane = size * size;
  const predictions: Box[] = [];
  let done = 0;

  for (const y of ys) {
    for (const x of xs) {
      // PIL's crop pads past the edge rather than resizing; clearing to black matches it.
      ctx.clearRect(0, 0, size, size);
      ctx.fillStyle = '#000';
      ctx.fillRect(0, 0, size, size);
      ctx.drawImage(source, x, y, size, size, 0, 0, size, size);
      const { data } = ctx.getImageData(0, 0, size, size);
      for (let p = 0, q = 0; p < plane; p++, q += 4) {
        input[p] = data[q] / 255;
        input[plane + p] = data[q + 1] / 255;
        input[2 * plane + p] = data[q + 2] / 255;
      }

      const output = await run(input);
      const local = nms(
        decode(output.data, output.dims, config.inference_confidence_floor),
        config.tile_nms_iou,
        config.max_detections_per_tile,
      );
      for (const b of local) {
        const box: Box = [
          Math.max(0, Math.min(1, (b[0] + x) / width)),
          Math.max(0, Math.min(1, (b[1] + y) / height)),
          Math.max(0, Math.min(1, (b[2] + x) / width)),
          Math.max(0, Math.min(1, (b[3] + y) / height)),
          b[4],
        ];
        if (box[2] > box[0] && box[3] > box[1]) predictions.push(box);
      }

      done++;
      onProgress?.({ done, total });
      await new Promise((r) => setTimeout(r, 0)); // keep the tab responsive between tiles
    }
  }

  return { boxes: nms(predictions, config.global_nms_iou), tiles: total };
}
