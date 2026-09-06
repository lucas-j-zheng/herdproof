"""Known-identity edge benchmark made from controlled crops of local drone photos.

This tests overlap logic independently of YOLO. Identities come from the original
annotation indices, not the matcher's predictions. Crop windows simulate camera
translation; animals are stationary because each pair uses one original exposure.
"""
import argparse
from dataclasses import asdict
import importlib.util
import json
from pathlib import Path
import sys

import cv2
import numpy as np
from PIL import Image

import aerial_survey as current


SOURCES = ['90afc33b02c0', '330b4bde696b', 'e08d9c27bd62',
           'afec265ae16c', '1ec41800809f', '1a09755a118c']


def crop_observations(boxes, window):
    x, y, w, h = window
    visible, identities = [], []
    for ident, box in enumerate(boxes):
        clipped = np.asarray(box) - [x, y, x, y]
        clipped = np.clip(clipped, [0, 0, 0, 0], [w, h, w, h])
        if min(clipped[2:] - clipped[:2]) >= 2:
            visible.append((clipped / [w, h, w, h]).tolist())
            identities.append(ident)
    return visible, identities


def cases_for(box, width=1200, height=1000):
    x1, y1, x2, y2 = box
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    base = (round(cx - width / 2), round(cy - height / 2), width, height)
    for fraction in (.2, .5, .8):
        for edge in ('left', 'right', 'top', 'bottom'):
            x, y = base[:2]
            if edge == 'left': x = round(x2 - fraction * (x2 - x1))
            if edge == 'right': x = round(x1 + fraction * (x2 - x1) - width)
            if edge == 'top': y = round(y2 - fraction * (y2 - y1))
            if edge == 'bottom': y = round(y1 + fraction * (y2 - y1) - height)
            yield f'{edge}-{fraction:.0%}', base, (x, y, width, height)
    for horizontal, vertical in [('left', 'top'), ('right', 'top'), ('left', 'bottom'), ('right', 'bottom')]:
        x = round(cx if horizontal == 'left' else cx - width)
        y = round(cy if vertical == 'top' else cy - height)
        yield horizontal + '-' + vertical, base, (x, y, width, height)


def save_window(original, window, path):
    x, y, w, h = window
    original.crop((x, y, x + w, y + h)).save(path, quality=95)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=Path('validation/data'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--implementation', type=Path, help='Optional frozen baseline Python implementation')
    parser.add_argument('--sources', nargs='+', default=SOURCES)
    args = parser.parse_args()
    survey = current
    if args.implementation:
        spec = importlib.util.spec_from_file_location('edge_baseline', args.implementation)
        survey = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = survey
        spec.loader.exec_module(survey)
    config = survey.Config()
    cv2.setNumThreads(2)
    args.output.mkdir(parents=True, exist_ok=True)
    manifest_path = args.data / 'manifest.json'
    records = {r['id']: r for r in json.loads(manifest_path.read_text())['records']}
    results = []
    for source in args.sources:
        record = records[source]
        path = args.data / record['image']
        if survey.sha256(path) != record['image_sha256']:
            raise ValueError('Image hash mismatch: ' + str(path))
        with Image.open(path) as image:
            original = image.convert('RGB')
        boxes = np.asarray(record['boxes']) * [original.width, original.height, original.width, original.height]
        interior = [i for i, b in enumerate(boxes) if 1300 < b[0] + b[2] < 2 * original.width - 1300
                    and 1100 < b[1] + b[3] < 2 * original.height - 1100]
        if not interior:
            raise ValueError('No interior target in ' + source)
        target = max(interior, key=lambda i: np.prod(boxes[i, 2:] - boxes[i, :2]))
        cache = {}
        for name, wa, wb in cases_for(boxes[target]):
            frames, observations, identities, ids = [], [], [], []
            for window in (wa, wb):
                if window not in cache:
                    norm_boxes, gt_ids = crop_observations(boxes, window)
                    ident = f'{source}-{len(cache)}'
                    crop_path = args.output / (ident + '.jpg')
                    save_window(original, window, crop_path)
                    cache[window] = (survey.prepare(crop_path, norm_boxes, config), norm_boxes, gt_ids, ident)
                frame, obs, gt_ids, ident = cache[window]
                frames.append(frame); observations.append(obs); identities.append(gt_ids); ids.append(ident)
            expected = {(i, j) for i, identity in enumerate(identities[0])
                        for j, other in enumerate(identities[1]) if identity == other}
            reg = survey.register(*frames, config)
            row = dict(source=source, case=name, target_identity=target, a=ids[0], b=ids[1],
                       windows=[wa, wb], registration=reg, expected_matches=sorted(expected),
                       expected_unique=len(set(identities[0]) | set(identities[1])))
            if reg['accepted']:
                association = survey.associate(*frames, np.asarray(reg['homography_a_to_b']), config)
                predicted = {(m['a'], m['b']) for m in association['matches']}
                row['association'] = association
                row['missing'] = sorted(expected - predicted)
                row['wrong'] = sorted(predicted - expected)
                row['target_matched'] = any(identities[0][i] == target for i, j in predicted & expected)
                recs = [dict(id=ident, observations=obs) for ident, obs in zip(ids, observations)]
                tracks = survey.build_tracks(recs, [dict(a=ids[0], b=ids[1], registration=reg, association=association)])
                row['estimated_unique'] = tracks['estimated_unique_observed']
                row['passed'] = not row['missing'] and not row['wrong'] and row['expected_unique'] == row['estimated_unique']
            else:
                row.update(passed=False, target_matched=False, missing=sorted(expected), wrong=[])
            results.append(row)
        group = [r for r in results if r['source'] == source]
        print(f"{source}: {sum(r['passed'] for r in group)}/{len(group)} exact cases; "
              f"{sum(r['target_matched'] for r in group)}/{len(group)} target edge cows matched", flush=True)
    summary = dict(cases=len(results), exact_cases=sum(r['passed'] for r in results),
                   registrations_passed=sum(r['registration']['accepted'] for r in results),
                   target_edge_cows_matched=sum(r['target_matched'] for r in results),
                   expected_matches=sum(len(r['expected_matches']) for r in results),
                   missed_matches=sum(len(r['missing']) for r in results), wrong_matches=sum(len(r['wrong']) for r in results))
    report = dict(summary=summary, source_images=args.sources, config=asdict(config),
                  implementation_sha256=survey.sha256(survey.__file__), evaluator_sha256=survey.sha256(__file__),
                  manifest_sha256=survey.sha256(manifest_path),
                  scope='Controlled stationary-cow crops with known identities; not real-flight accuracy.', results=results)
    (args.output / 'report.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    print(json.dumps(summary), flush=True)
    return 0 if summary['exact_cases'] == summary['cases'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
