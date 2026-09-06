"""Experimental duplicate removal across nearby aerial photographs.

Uses existing detections (or explicitly requested annotations), background SIFT
registration and conservative one-to-one association. No drone control, new model
inference, identity ground truth, or claim of complete property coverage.

Run from the repository root with the dependencies pinned in
training/environment/pyproject.toml (no model needs to be loaded):

    python scripts/aerial_survey.py --data /path/to/photos --run /path/to/predictions --output /path/to/survey
    python scripts/aerial_survey.py --data /path/to/photos --labels --output /path/to/annotation-audit
    python -m unittest discover -s scripts -p 'test_aerial_survey*.py'

The photo directory's manifest.json contains a records list with id, image,
image_sha256 and flight; --labels additionally requires normalized xyxy boxes.
Original JPEGs need EXIF GPS and capture times. Saved predictions use report.json
selection.selected_mode/selected_threshold and one <id>.json per photograph,
containing matching id/image_sha256 and modes[mode].boxes (xyxy plus confidence).
This is also the output format of training.infer. Missing predictions fail unless
--skip-missing-predictions is explicitly requested; annotations are never a fallback.

Output report.json records pairwise registration, inferred tracks, one estimated
count per track, preferred views and unresolved edge recapture targets. Ambiguous
identities stay separate and clipped sightings stay explicit. Supplied-box edge
tests establish geometry behavior, not detector accuracy or a verified herd total.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import itertools
import json
import math
from pathlib import Path
import re

import cv2
import numpy as np
from PIL import Image, ImageDraw
from scipy.optimize import linear_sum_assignment


@dataclass(frozen=True)
class Config:
    max_seconds: float = 30.0
    max_distance_m: float = 160.0
    working_width: int = 1600
    min_inliers: int = 40
    min_inlier_ratio: float = 0.35
    min_overlap: float = 0.12
    max_median_error_px: float = 2.0
    max_center_distance: float = 0.8  # In cow-box diagonals, not GPS metres.
    ambiguity_margin: float = 0.18
    edge_margin: float = 0.05
    clipped_margin: float = 0.001
    min_shared_area_px: float = 4.0
    min_shared_span_px: float = 1.5
    min_edge_iou: float = 0.15


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def metadata(path):
    with Image.open(path) as im:
        exif = im.getexif()
        gps, detail = exif.get_ifd(34853), exif.get_ifd(34665)
        def degrees(key, ref):
            value = sum(float(v) / d for v, d in zip(gps[key], (1, 60, 3600)))
            return -value if gps[ref] in ('S', 'W') else value
        result = dict(width=im.width, height=im.height, camera=exif.get(272),
                      lat=degrees(2, 1), lon=degrees(4, 3),
                      captured=datetime.strptime(detail[36867], '%Y:%m:%d %H:%M:%S').isoformat())
    with Path(path).open('rb') as stream:
        xmp = dict(re.findall(r'drone-dji:(\w+)="([^"]+)"', stream.read(150000).decode('latin1')))
    for field in ('RelativeAltitude', 'GimbalYawDegree', 'GimbalPitchDegree'):
        result[field] = float(xmp[field]) if field in xmp else None
    if not (-90 <= result['lat'] <= 90 and -180 <= result['lon'] <= 180):
        raise ValueError('Invalid GPS coordinates')
    return result


def distance_m(a, b):
    lat1, lat2 = math.radians(a['lat']), math.radians(b['lat'])
    dlat, dlon = lat2 - lat1, math.radians(b['lon'] - a['lon'])
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371000 * 2 * math.asin(math.sqrt(min(1, max(0, h))))


def candidate_pairs(records, config):
    """Never associate different flights or dates, even if filenames suggest otherwise."""
    for a, b in itertools.combinations(sorted(records, key=lambda r: r['meta']['captured']), 2):
        if a['flight'] != b['flight']:
            continue
        ta, tb = (datetime.fromisoformat(r['meta']['captured']) for r in (a, b))
        seconds = abs((tb - ta).total_seconds())
        distance = distance_m(a['meta'], b['meta'])
        if ta.date() == tb.date() and seconds <= config.max_seconds and distance <= config.max_distance_m:
            yield a, b, seconds, distance


def validate_boxes(boxes):
    array = np.asarray(boxes, dtype=np.float64)
    if array.size == 0:
        return []
    if array.ndim != 2 or array.shape[1] != 4 or not np.isfinite(array).all():
        raise ValueError('Expected finite normalized xyxy boxes')
    # YOLO conversion can overshoot an edge by a rounding unit.
    if np.any(array < -1e-5) or np.any(array > 1 + 1e-5):
        raise ValueError('Box lies outside normalized image coordinates')
    array = np.clip(array, 0, 1)
    if np.any(array[:, 2:] <= array[:, :2]):
        raise ValueError('Box has zero or negative area')
    return array.tolist()


def observations(record, run, selection):
    if run is None:
        return validate_boxes(record['boxes'])
    path = Path(run) / (record['id'] + '.json')
    payload = json.loads(path.read_text())  # Missing predictions must fail; never use labels.
    if payload.get('id') != record['id'] or payload.get('image_sha256') != record['image_sha256']:
        raise ValueError(f'Prediction provenance mismatch: {path}')
    raw = payload['modes'][selection['selected_mode']]['boxes']
    if any(len(b) != 5 or not math.isfinite(b[4]) or not 0 <= b[4] <= 1 for b in raw):
        raise ValueError(f'Invalid confidence values: {path}')
    return validate_boxes([b[:4] for b in raw if b[4] >= selection['selected_threshold']])


def edge_flags(boxes, margin=0.05):
    """Image-relative recapture hints, not world directions or flight commands."""
    result = []
    for index, (x1, y1, x2, y2) in enumerate(boxes):
        edges = [name for name, near in (('left', x1 <= margin), ('right', x2 >= 1 - margin),
                 ('top', y1 <= margin), ('bottom', y2 >= 1 - margin)) if near]
        if edges:
            result.append({'detection': index, 'image_edges': edges})
    return result


def prepare(path, boxes, config):
    with Image.open(path) as im:
        im = im.convert('RGB')
        im.thumbnail((config.working_width, config.working_width), Image.Resampling.LANCZOS)
        rgb = np.array(im)
    h, w = rgb.shape[:2]
    pixel_boxes = np.asarray(boxes, dtype=np.float64).reshape(-1, 4) * [w, h, w, h]
    mask = np.full((h, w), 255, dtype=np.uint8)
    appearance = []
    for x1, y1, x2, y2 in pixel_boxes:
        # Mask cows and their immediate surroundings to register static background.
        pad = max(8, 0.4 * max(x2 - x1, y2 - y1))
        cv2.rectangle(mask, (max(0, int(x1 - pad)), max(0, int(y1 - pad))),
                      (min(w - 1, math.ceil(x2 + pad)), min(h - 1, math.ceil(y2 + pad))), 0, -1)
        crop = rgb[max(0, int(y1)):min(h, math.ceil(y2)), max(0, int(x1)):min(w, math.ceil(x2))]
        lab = cv2.cvtColor(crop, cv2.COLOR_RGB2LAB)
        hist = cv2.calcHist([lab], [0, 1, 2], None, [8, 4, 4], [0, 256] * 3).ravel()
        appearance.append(hist / max(float(hist.sum()), 1))
    keypoints, descriptors = cv2.SIFT_create(nfeatures=7000).detectAndCompute(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY), mask)
    return dict(rgb=rgb, boxes=pixel_boxes, appearance=appearance, descriptors=descriptors,
                points=np.asarray([k.pt for k in keypoints], dtype=np.float32).reshape(-1, 2))


def transform(points, homography):
    return cv2.perspectiveTransform(np.asarray(points, dtype=np.float64).reshape(-1, 1, 2), homography).reshape(-1, 2)


def frame_polygon(frame):
    h, w = frame['rgb'].shape[:2]
    return np.float32([[0, 0], [w, 0], [w, h], [0, h]])


def register(a, b, config):
    result = {'accepted': False}
    def reject(reason):
        return {**result, 'reason': reason}
    if a['descriptors'] is None or b['descriptors'] is None or min(len(a['points']), len(b['points'])) < 4:
        return reject('insufficient_background_features')
    knn = cv2.BFMatcher().knnMatch(a['descriptors'], b['descriptors'], k=2)
    good = [pair[0] for pair in knn if len(pair) == 2 and pair[0].distance < 0.7 * pair[1].distance]
    # Each background feature contributes at most one vote.
    unique = {}
    for match in sorted(good, key=lambda m: m.distance):
        unique.setdefault(match.trainIdx, match)
    good = list(unique.values())
    result['feature_matches'] = len(good)
    if len(good) < config.min_inliers:
        return reject('too_few_feature_matches')
    pa = np.float32([a['points'][m.queryIdx] for m in good])
    pb = np.float32([b['points'][m.trainIdx] for m in good])
    cv2.setRNGSeed(0)
    homography, mask = cv2.findHomography(pa, pb, cv2.RANSAC, 3.0, maxIters=4000, confidence=0.999)
    if homography is None or not np.isfinite(homography).all():
        return reject('homography_failed')
    inliers = mask.ravel().astype(bool)
    result.update(inliers=int(inliers.sum()), inlier_ratio=float(inliers.mean()))
    if result['inliers'] < config.min_inliers or result['inlier_ratio'] < config.min_inlier_ratio:
        return reject('weak_registration')
    corners = frame_polygon(a)
    denominators = corners @ homography[2, :2] + homography[2, 2]
    if np.any(np.abs(denominators) < 1e-8) or np.min(denominators) * np.max(denominators) <= 0:
        return reject('projection_crosses_horizon')
    projected = transform(corners, homography).astype(np.float32)
    source_area = cv2.contourArea(corners, oriented=True)
    projected_area = cv2.contourArea(projected, oriented=True)
    if not cv2.isContourConvex(projected) or not 0.4 <= projected_area / source_area <= 2.5:
        return reject('implausible_footprint')
    target = frame_polygon(b)
    overlap_area, _ = cv2.intersectConvexConvex(projected, target)
    overlap = overlap_area / min(projected_area, cv2.contourArea(target))
    residuals = np.linalg.norm(transform(pa[inliers], homography) - pb[inliers], axis=1)
    # Require matches spread over a meaningful area, not one ambiguous grass patch.
    support = cv2.contourArea(cv2.convexHull(pb[inliers])) / max(overlap_area, 1)
    result.update(overlap_fraction=float(overlap), median_error_px=float(np.median(residuals)),
                  background_support_fraction=float(support))
    if overlap < config.min_overlap or support < 0.10 or result['median_error_px'] > config.max_median_error_px:
        return reject('insufficient_overlap_or_spatial_support')
    return {**result, 'accepted': True, 'homography_a_to_b': homography.tolist(),
            'projected_a_corners': projected.tolist(), 'reason': 'background_verified'}


def box_polygon(box):
    x1, y1, x2, y2 = box
    return np.float32([[x1, y1], [x2, y1], [x2, y2], [x1, y2]])


def polygon_intersection(a, b):
    """Convex clipping in float64, including coincident frame boundaries.

    Avoid intersectConvexConvex here: almost-collinear boundary intersections in
    these images can return the enclosing frame instead of the small cow box.
    """
    if a is None or b is None or len(a) < 3 or len(b) < 3:
        return np.empty((0, 2), dtype=np.float32)
    points, boundary = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    signed_area = np.sum(boundary[:, 0] * np.roll(boundary[:, 1], -1) - boundary[:, 1] * np.roll(boundary[:, 0], -1))
    if signed_area < 0:
        boundary = boundary[::-1]
    for start, end in zip(boundary, np.roll(boundary, -1, axis=0)):
        edge = end - start
        length = np.linalg.norm(edge)
        if length < 1e-9:
            continue
        if len(points) < 3:
            return np.empty((0, 2), dtype=np.float32)
        delta = points - start
        distances = (edge[0] * delta[:, 1] - edge[1] * delta[:, 0]) / length
        output = []
        previous, dp = points[-1], distances[-1]
        for point, distance in zip(points, distances):
            inside, was_inside = distance >= -1e-8, dp >= -1e-8
            if inside != was_inside:
                output.append(previous + (point - previous) * dp / (dp - distance))
            if inside:
                output.append(point)
            previous, dp = point, distance
        points = np.asarray(output).reshape(-1, 2)
    if len(points) < 3 or cv2.contourArea(points.astype(np.float32)) <= 1e-5:
        return np.empty((0, 2), dtype=np.float32)
    return points.astype(np.float32)


def shared_observations(frame, homography, common, config):
    """Describe only the part of each observation visible in BOTH photographs."""
    result = []
    h, w = frame['rgb'].shape[:2]
    for box in frame['boxes']:
        polygon = transform(box_polygon(box), homography).astype(np.float32)
        visible = polygon_intersection(polygon, common)
        area = cv2.contourArea(visible) if len(visible) >= 3 else 0
        fraction = area / max(cv2.contourArea(polygon), 1e-6)
        span = np.ptp(visible, axis=0) if len(visible) else np.zeros(2)
        valid = area >= config.min_shared_area_px and min(span) >= config.min_shared_span_px
        moments = cv2.moments(visible) if valid else None
        center = ([moments['m10'] / moments['m00'], moments['m01'] / moments['m00']]
                  if valid else [0., 0.])
        normalized = box / [w, h, w, h]
        touches = min(normalized[0], normalized[1], 1 - normalized[2], 1 - normalized[3]) <= config.clipped_margin
        result.append(dict(polygon=visible, area=area, fraction=fraction, valid=valid,
                           center=center, size=float(np.linalg.norm(span)), clipped=touches or fraction < .98))
    return result


def associate(a, b, homography, config):
    """Partial assignment using shared visible regions, including clipped cows.

    A full box's centre may be outside the other image while its head or tail is
    still visible. Compare both boxes AFTER clipping to the common footprint;
    never extrapolate a clipped observation into an invented whole animal.
    """
    ba, bb = a['boxes'], b['boxes']
    common = polygon_intersection(transform(frame_polygon(a), homography), frame_polygon(b))
    va = shared_observations(a, homography, common, config)
    vb = shared_observations(b, np.eye(3), common, config)
    empty = {'matches': [], 'ambiguous': [], 'eligible_edges': 0}
    if not len(ba) or not len(bb):
        return {**empty, 'unmatched_a': [{'detection': i, 'reason': 'no_counterpart_detections'} for i in range(len(ba))],
                'unmatched_b': [{'detection': i, 'reason': 'no_counterpart_detections'} for i in range(len(bb))]}
    centers, other = (np.asarray([v['center'] for v in values]) for values in (va, vb))
    size_a, size_b = (np.asarray([v['size'] for v in values]) for values in (va, vb))
    sizes = np.maximum(4, (size_a[:, None] + size_b[None, :]) / 2)
    distance = np.linalg.norm(centers[:, None, :] - other[None, :, :], axis=2) / sizes
    ratio = size_a[:, None] / np.maximum(size_b[None, :], 1)
    valid = np.asarray([v['valid'] for v in va])[:, None] & np.asarray([v['valid'] for v in vb])[None, :]
    clipped = np.asarray([v['clipped'] for v in va])[:, None] | np.asarray([v['clipped'] for v in vb])[None, :]
    ious = np.zeros((len(ba), len(bb)))
    for i, j in zip(*np.where(valid & clipped)):
        polygon = polygon_intersection(va[i]['polygon'], vb[j]['polygon'])
        area = cv2.contourArea(polygon) if len(polygon) >= 3 else 0
        ious[i, j] = area / max(va[i]['area'] + vb[j]['area'] - area, 1e-6)
    appearance = np.asarray([[math.sqrt(max(0, 1 - float(np.sqrt(x * y).sum())))
                              for y in b['appearance']] for x in a['appearance']])
    # Partial and complete cows need not have the same colour histogram. Geometry
    # of the shared portion dominates those matches; appearance remains a weak cue.
    costs = distance + np.where(clipped, .1, .25) * appearance + np.where(clipped, .25 * (1 - ious), 0)
    eligible = valid & (distance <= config.max_center_distance) & (ratio >= 0.5) & (ratio <= 2)
    eligible &= ~clipped | (ious >= config.min_edge_iou)
    costs = np.where(eligible, costs, 1e6)
    # Each source has an independent unmatched option; target columns remain unique.
    padded = np.concatenate([costs, np.full((len(ba), len(ba)), config.max_center_distance + 0.26)], axis=1)
    rows, cols = linear_sum_assignment(padded)
    matches, ambiguous = [], []
    for i, j in zip(rows, cols):
        if j >= len(bb) or not eligible[i, j]:
            continue
        competing = min(np.min(np.delete(costs[i], j), initial=1e6),
                        np.min(np.delete(costs[:, j], i), initial=1e6))
        item = dict(a=int(i), b=int(j), cost=float(costs[i, j]),
                    distance_in_box_diagonals=float(distance[i, j]), appearance_distance=float(appearance[i, j]),
                    method='shared_edge_region' if clipped[i, j] else 'interior_position',
                    shared_iou=float(ious[i, j]) if clipped[i, j] else None,
                    shared_fraction_a=float(va[i]['fraction']), shared_fraction_b=float(vb[j]['fraction']))
        if competing - costs[i, j] < config.ambiguity_margin:
            ambiguous.append(item)
        else:
            matches.append(item)
    def unmatched(side, values):
        matched = {m[side] for m in matches}
        uncertain = {m[side] for m in ambiguous}
        return [{'detection': i, 'reason': ('outside_or_tiny_shared_region' if not v['valid'] else
                 'ambiguous_identity' if i in uncertain else 'no_reliable_counterpart')}
                for i, v in enumerate(values) if i not in matched]
    return {'matches': matches, 'ambiguous': ambiguous, 'eligible_edges': int(eligible.sum()),
            'unmatched_a': unmatched('a', va), 'unmatched_b': unmatched('b', vb)}


def build_tracks(records, pairs):
    parent, members = {}, {}
    for record in records:
        for index in range(len(record['observations'])):
            key = (record['id'], index)
            parent[key], members[key] = key, {key[0]}
    def root(key):
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key
    edges = sorted((m['cost'], p['a'], m['a'], p['b'], m['b']) for p in pairs
                   if p['registration']['accepted'] for m in p['association']['matches'])
    rejected, merges = [], 0
    for cost, a, ai, b, bi in edges:
        ra, rb = root((a, ai)), root((b, bi))
        if ra == rb:
            continue
        if members[ra] & members[rb]:
            rejected.append({'a': [a, ai], 'b': [b, bi], 'cost': cost, 'reason': 'two_observations_from_same_photo'})
            continue
        parent[rb] = ra
        members[ra] |= members.pop(rb)
        merges += 1
    tracks = defaultdict(list)
    for key in sorted(parent):
        tracks[root(key)].append(list(key))
    return {'estimated_unique_observed': len(tracks), 'raw_observations': len(parent),
            'deduplication_merges': merges, 'conflicting_associations': rejected,
            'tracks': list(tracks.values())}


def summarize_track_edges(records, tracks, config):
    """Resolve clipped sightings with a full view already in the same track.

    A recapture target stays pending if all available views are clipped. Nothing
    is discarded, and merely being near an edge never creates an identity link.
    """
    by_id = {r['id']: r for r in records}
    events, pending, preferred = [], [], []
    for track_id, track in enumerate(tracks):
        def clearance(member):
            box = by_id[member[0]]['observations'][member[1]]
            return min(box[0], box[1], 1 - box[2], 1 - box[3])
        best = max(track, key=clearance)
        preferred.append({'track_id': track_id, 'observation': best})
        track_pending = []
        for image_id, index in track:
            box = by_id[image_id]['observations'][index]
            flags = edge_flags([box], config.edge_margin)
            if not flags:
                continue
            clipped = clearance([image_id, index]) <= config.clipped_margin
            resolved = clipped and clearance(best) > config.clipped_margin
            event = dict(track_id=track_id, observation=[image_id, index],
                         image_edges=flags[0]['image_edges'], clipped=clipped,
                         status='resolved_in_another_photo' if resolved else
                                'recapture_needed' if clipped else 'fully_visible_near_edge',
                         resolved_by=best if resolved else None)
            events.append(event)
            if clipped and not resolved:
                track_pending.append(event)
        if track_pending:
            box = by_id[best[0]]['observations'][best[1]]
            pending.append(dict(track_id=track_id, reference_observation=best,
                                image_edges=edge_flags([box], config.clipped_margin)[0]['image_edges'],
                                image_point=[(box[0] + box[2]) / 2, (box[1] + box[3]) / 2],
                                reason='All linked views are clipped; obtain a full view if possible.'))
    return dict(edge_observations=events, preferred_observations=preferred, recapture_targets=pending,
                clipped_observations=sum(e['clipped'] for e in events),
                clipped_resolved_in_other_photo=sum(e['status'] == 'resolved_in_another_photo' for e in events),
                unresolved_clipped_tracks=len(pending),
                count_status='needs_edge_recapture' if pending else 'proposed')


def render_pair(a, b, pair, path, source):
    """Analytical evidence image with common IDs for pairwise accepted associations."""
    images = [Image.fromarray(frame['rgb']) for frame in (a, b)]
    width = 1100
    panels = []
    matches = pair.get('association', {}).get('matches', [])
    for side, (frame, im) in enumerate(zip((a, b), images)):
        scale = width / im.width
        im = im.resize((width, round(im.height * scale)))
        panel = Image.new('RGB', (width, im.height + 64), '#132021')
        panel.paste(im, (0, 64))
        draw = ImageDraw.Draw(panel)
        ident = pair['a' if side == 0 else 'b']
        draw.text((16, 12), f"{ident} | {len(frame['boxes'])} {source} boxes", fill='white', font_size=20)
        draw.text((16, 37), 'Green: proposed same cow (M#)   Orange: unmatched', fill='white', font_size=16)
        ids = {m['a' if side == 0 else 'b']: k + 1 for k, m in enumerate(matches)}
        for index, box in enumerate(frame['boxes']):
            x1, y1, x2, y2 = box * scale
            y1 += 64
            y2 += 64
            color = '#33ff99' if index in ids else '#ffb347'
            draw.rectangle((x1, y1, x2, y2), outline=color, width=2)
            text = f'M{ids[index]}' if index in ids else f'#{index}'
            draw.text((x1, max(64, y1 - 20)), text, fill=color, stroke_width=1, stroke_fill='black', font_size=16)
        panels.append(panel)
    canvas = Image.new('RGB', (2 * width, max(p.height for p in panels) + 84), '#132021')
    for index, panel in enumerate(panels):
        canvas.paste(panel, (index * width, 0))
    draw = ImageDraw.Draw(canvas)
    reg = pair['registration']
    draw.text((16, canvas.height - 72),
              f"{pair['seconds_apart']:g}s apart | {reg['inliers']} background inliers | "
              f"{reg['overlap_fraction']:.0%} overlap | {len(matches)} proposed duplicate pairs", fill='white', font_size=24)
    draw.text((16, canvas.height - 37), 'Experimental association; no cross-photo identity labels. This is not a verified herd total.',
              fill='#b9ceca', font_size=20)
    canvas.save(path)


def render_match_crops(records, data, pair, path):
    """Show original-resolution cow crops so proposed identities can be inspected."""
    by_id = {r['id']: r for r in records}
    matches = pair['association']['matches'][:12]
    if not matches:
        return
    originals = []
    for key in ('a', 'b'):
        with Image.open(data / by_id[pair[key]]['image']) as im:
            originals.append(im.convert('RGB'))
    card_w, card_h = 500, 278
    sheet = Image.new('RGB', (card_w * 3, math.ceil(len(matches) / 3) * card_h + 64), '#132021')
    draw = ImageDraw.Draw(sheet)
    draw.text((16, 12), 'Proposed same-cow matches | left: earlier photo, right: later photo', fill='white', font_size=22)
    draw.text((16, 39), 'Original photo crops. These IDs are inferred, not provided by the dataset.', fill='#b9ceca', font_size=17)
    for index, match in enumerate(matches):
        x, y = (index % 3) * card_w, 64 + (index // 3) * card_h
        draw.text((x + 12, y + 5), f'M{index + 1}', fill='#33ff99', font_size=21)
        for side, key in enumerate(('a', 'b')):
            im = originals[side]
            box = np.asarray(by_id[pair[key]]['observations'][match[key]]) * [im.width, im.height, im.width, im.height]
            cx, cy = (box[:2] + box[2:]) / 2
            half = 1.5 * max(box[2] - box[0], box[3] - box[1])
            crop = im.crop((round(cx - half), round(cy - half), round(cx + half), round(cy + half)))
            crop = crop.resize((238, 238), Image.Resampling.LANCZOS)
            sheet.paste(crop, (x + 8 + side * 246, y + 33))
    sheet.save(path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--data', type=Path, default=Path('validation/data'))
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--labels', action='store_true', help='Diagnostic association of annotations, not detector evaluation')
    source.add_argument('--run', type=Path, help='Existing saved detector run with report.json selection')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--flight', help='Exact flight name from manifest; default all')
    parser.add_argument('--skip-missing-predictions', action='store_true',
                        help='Explicitly exclude photos without saved predictions and list them in quarantined')
    parser.add_argument('--max-seconds', type=float, default=30)
    parser.add_argument('--max-distance-m', type=float, default=160)
    parser.add_argument('--evidence-pairs', type=int, default=6)
    args = parser.parse_args(argv)
    if args.skip_missing_predictions and not args.run:
        parser.error('--skip-missing-predictions requires --run')
    if args.max_seconds <= 0 or args.max_distance_m <= 0 or args.evidence_pairs < 0:
        parser.error('Time/distance must be positive and evidence count nonnegative')
    config = Config(max_seconds=args.max_seconds, max_distance_m=args.max_distance_m)
    cv2.setNumThreads(2)
    manifest_path = args.data / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    records = [dict(r) for r in manifest['records'] if args.flight is None or r['flight'] == args.flight]
    if not records or len({r['id'] for r in records}) != len(records):
        parser.error('No records selected, or duplicate image IDs')
    selection = None
    if args.run:
        selection = json.loads((args.run / 'report.json').read_text())['selection']
        if not 0 <= selection['selected_threshold'] <= 1:
            parser.error('Invalid saved detector threshold')
    groups, quarantined = defaultdict(list), []
    for record in records:
        path = args.data / record['image']
        if args.run and args.skip_missing_predictions and not (args.run / (record['id'] + '.json')).exists():
            quarantined.append({'id': record['id'], 'reason': 'missing_prediction'})
            continue
        if sha256(path) != record['image_sha256']:
            raise ValueError(f'Image hash mismatch: {path}')
        record['observations'] = observations(record, args.run, selection)
        try:
            record['meta'] = metadata(path)
        except (KeyError, ValueError, TypeError, ZeroDivisionError) as exc:
            quarantined.append({'id': record['id'], 'reason': f'metadata: {exc}'})
            continue
        groups[record['flight']].append(record)
    args.output.mkdir(parents=True, exist_ok=True)
    flights, all_pairs, evidence_count = {}, [], 0
    for flight, group in sorted(groups.items()):
        pairs, frames = [], {}
        for a, b, seconds, distance in candidate_pairs(group, config):
            for record in (a, b):
                if record['id'] not in frames:
                    frames[record['id']] = prepare(args.data / record['image'], record['observations'], config)
            fa, fb = frames[a['id']], frames[b['id']]
            registration = register(fa, fb, config)
            pair = dict(a=a['id'], b=b['id'], seconds_apart=seconds, camera_distance_m=distance, registration=registration)
            if registration['accepted']:
                pair['association'] = associate(fa, fb, np.asarray(registration['homography_a_to_b']), config)
            pairs.append(pair)
        # Prefer short-time, many-match examples; total saved across flights is bounded.
        choices = sorted((p for p in pairs if p['registration']['accepted'] and p['association']['matches']),
                         key=lambda p: (p['seconds_apart'], -len(p['association']['matches'])))
        for pair in choices[:max(0, args.evidence_pairs - evidence_count)]:
            filename = f"pair-{pair['a']}-{pair['b']}.jpg"
            render_pair(frames[pair['a']], frames[pair['b']], pair, args.output / filename,
                        'annotation' if args.labels else 'model')
            pair['evidence_image'] = filename
            crop_filename = filename.replace('.jpg', '-crops.jpg')
            render_match_crops(group, args.data, pair, args.output / crop_filename)
            pair['evidence_crops'] = crop_filename
            evidence_count += 1
        track_result = build_tracks(group, pairs)
        flights[flight] = {**track_result, **summarize_track_edges(group, track_result['tracks'], config),
                          'images': len(group), 'candidate_pairs': len(pairs),
                          'verified_overlap_pairs': sum(p['registration']['accepted'] for p in pairs)}
        all_pairs.extend(pairs)
        print(f"{flight}: {flights[flight]['verified_overlap_pairs']}/{len(pairs)} overlap pairs; "
              f"{flights[flight]['raw_observations']} observations -> {flights[flight]['estimated_unique_observed']} proposed tracks", flush=True)
    valid = [r for group in groups.values() for r in group]
    observation_counts = {r['id']: len(r['observations']) for r in valid}
    report = dict(schema_version=2, status='experimental_not_identity_validated',
                  source='annotations' if args.labels else 'saved_model_predictions',
                  data=str(args.data.resolve()), run=str(args.run.resolve()) if args.run else None,
                  manifest_sha256=sha256(manifest_path), code_sha256=sha256(__file__),
                  run_report_sha256=sha256(args.run / 'report.json') if args.run else None,
                  skip_missing_predictions=args.skip_missing_predictions,
                  detector_selection=selection, config=asdict(config),
                  limitations=['No cross-photo identity ground truth; associations and unique counts are unvalidated.',
                               'Cow motion, similar appearance, missing detections and registration errors can cause over/undercount.',
                               'Sparse photographs do not establish complete property coverage or a true herd total.',
                               'Image-edge hints are recapture suggestions only; no drone control.'],
                  summary=dict(selected_images=len(records), processed_images=len(valid), flights=len(flights),
                               candidate_pairs=len(all_pairs), verified_overlap_pairs=sum(p['registration']['accepted'] for p in all_pairs),
                               edge_region_matches=sum(m.get('method') == 'shared_edge_region' for p in all_pairs
                                                       for m in p.get('association', {}).get('matches', [])),
                               clipped_resolved_in_other_photo=sum(f['clipped_resolved_in_other_photo'] for f in flights.values()),
                               unresolved_clipped_tracks=sum(f['unresolved_clipped_tracks'] for f in flights.values()),
                               labeled_overlap_pairs=sum(p['registration']['accepted'] and observation_counts[p['a']] > 0
                                                         and observation_counts[p['b']] > 0 for p in all_pairs) if args.labels else None),
                  quarantined=quarantined, flights=flights, pairs=all_pairs,
                  images=[dict(id=r['id'], flight=r['flight'], meta=r['meta'], observations=r['observations'],
                               image_sha256=r['image_sha256'], edge_recapture_hints=edge_flags(r['observations'], config.edge_margin)) for r in valid])
    (args.output / 'report.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    print(json.dumps(report['summary']), flush=True)
    return report


if __name__ == '__main__':
    main()
