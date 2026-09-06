"""Behavior checks for experimental cross-photo cattle association."""
import json
from pathlib import Path
import tempfile
import unittest

import cv2
import numpy as np

from aerial_survey import (Config, associate, build_tracks, candidate_pairs, edge_flags,
                           observations, register, transform, validate_boxes, polygon_intersection, box_polygon,
                           summarize_track_edges)


def frame(boxes):
    return {'rgb': np.zeros((400, 600, 3), dtype=np.uint8),
            'boxes': np.asarray(boxes, dtype=float).reshape(-1, 4),
            'appearance': [np.array([0.5, 0.5]) for _ in boxes]}


def record(ident, time, flight='flight', count=1):
    return {'id': ident, 'flight': flight, 'observations': [None] * count,
            'meta': {'captured': time, 'lat': 46.0, 'lon': 4.0}}


def pair(a, b, matches):
    return {'a': a, 'b': b, 'registration': {'accepted': True},
            'association': {'matches': [{'a': i, 'b': j, 'cost': cost} for i, j, cost in matches]}}


class AssociationTests(unittest.TestCase):
    def test_most_of_cow_clipped_on_all_four_edges(self):
        # A shows the whole cow; B shows only a fifth. In two cases the
        # projected full-cow centre is completely outside B's footprint.
        cases = [([100, 100, 200, 120], [-180, 0], [0, 100, 20, 120]),
                 ([100, 100, 200, 120], [480, 0], [580, 100, 600, 120]),
                 ([100, 100, 120, 200], [0, -180], [100, 0, 120, 20]),
                 ([100, 100, 120, 200], [0, 280], [100, 380, 120, 400])]
        for full, delta, clipped in cases:
            h = np.eye(3)
            h[:2, 2] = delta
            for a, b, matrix in ((frame([full]), frame([clipped]), h),
                                 (frame([clipped]), frame([full]), np.linalg.inv(h))):
                with self.subTest(full=full, delta=delta, reverse=matrix is not h):
                    result = associate(a, b, matrix, Config())
                    self.assertEqual([(m['a'], m['b']) for m in result['matches']], [(0, 0)])

    def test_edge_cow_does_not_merge_with_nearby_different_cow(self):
        a = frame([[100, 100, 200, 120]])
        b = frame([[0, 132, 20, 152]])
        h = np.array([[1., 0, -180], [0, 1, 0], [0, 0, 1]])
        self.assertEqual(associate(a, b, h, Config())['matches'], [])

    def test_new_cow_outside_shared_footprint_is_not_a_duplicate(self):
        a = frame([[580, 100, 600, 120]])
        b = frame([[205, 100, 225, 120]])
        h = np.array([[1., 0, -400], [0, 1, 0], [0, 0, 1]])
        # The old cow projects to x180..200. The new cow is beyond A's footprint,
        # which ends at x200 in B, so there is no common observation to merge.
        self.assertEqual(associate(a, b, h, Config())['matches'], [])

    def test_clipped_matches_survive_camera_rotation_and_scale(self):
        full = [250, 185, 350, 215]
        for angle in (0, 90, 180, 270):
            for scale in (.7, 1, 1.4):
                radians = np.deg2rad(angle)
                rotation = scale * np.array([[np.cos(radians), -np.sin(radians)],
                                             [np.sin(radians), np.cos(radians)]])
                corners = np.array([[250, 185], [350, 185], [350, 215], [250, 215]]) @ rotation.T
                extent = np.ptp(corners, axis=0)
                for edge in ('left', 'right', 'top', 'bottom'):
                    minimum = np.array([200., 100.])
                    if edge == 'left': minimum[0] = -.8 * extent[0]
                    if edge == 'right': minimum[0] = 600 - .2 * extent[0]
                    if edge == 'top': minimum[1] = -.8 * extent[1]
                    if edge == 'bottom': minimum[1] = 400 - .2 * extent[1]
                    h = np.eye(3)
                    h[:2, :2] = rotation
                    h[:2, 2] = minimum - corners.min(axis=0)
                    clipped = np.clip(np.r_[minimum, minimum + extent], [0, 0, 0, 0], [600, 400, 600, 400])
                    with self.subTest(angle=angle, scale=scale, edge=edge):
                        result = associate(frame([full]), frame([clipped]), h, Config())
                        self.assertEqual([(m['a'], m['b']) for m in result['matches']], [(0, 0)])

    def test_small_animal_movement_at_edge_is_tolerated(self):
        h = np.array([[1., 0, -180], [0, 1, 0], [0, 0, 1]])
        result = associate(frame([[100, 100, 200, 120]]), frame([[0, 103, 20, 123]]), h, Config())
        self.assertEqual([(m['a'], m['b']) for m in result['matches']], [(0, 0)])

    def test_subpixel_edge_sliver_is_reported_unmatched(self):
        h = np.array([[1., 0, -199.8], [0, 1, 0], [0, 0, 1]])
        result = associate(frame([[100, 100, 200, 120]]), frame([[0, 100, .2, 120]]), h, Config())
        self.assertEqual(result['matches'], [])
        self.assertEqual(result['unmatched_a'][0]['reason'], 'outside_or_tiny_shared_region')

    def test_two_ambiguous_clipped_cows_are_not_forcibly_merged(self):
        h = np.array([[1., 0, -180], [0, 1, 0], [0, 0, 1]])
        result = associate(frame([[100, 100, 200, 120]]),
                           frame([[0, 99, 20, 119], [0, 101, 20, 121]]), h, Config())
        self.assertEqual(result['matches'], [])
        self.assertEqual(len(result['ambiguous']), 1)

    def test_translation_and_unmatched_cow(self):
        a = frame([[10, 10, 30, 30], [100, 100, 120, 120]])
        b = frame([[150, 100, 170, 120], [60, 10, 80, 30], [400, 300, 420, 320]])
        h = np.array([[1., 0, 50], [0, 1, 0], [0, 0, 1]])
        result = associate(a, b, h, Config())
        self.assertEqual({(m['a'], m['b']) for m in result['matches']}, {(0, 1), (1, 0)})

    def test_near_identical_cows_are_ambiguous(self):
        a = frame([[10, 10, 30, 30]])
        b = frame([[8, 10, 28, 30], [12, 10, 32, 30]])
        result = associate(a, b, np.eye(3), Config())
        self.assertEqual(result['matches'], [])
        self.assertEqual(len(result['ambiguous']), 1)

    def test_one_target_cannot_match_two_sources(self):
        a = frame([[10, 10, 30, 30], [17, 10, 37, 30]])
        b = frame([[10, 10, 30, 30]])
        result = associate(a, b, np.eye(3), Config())
        self.assertEqual([(m['a'], m['b']) for m in result['matches']], [(0, 0)])

    def test_distant_cow_not_forced_into_match(self):
        result = associate(frame([[0, 0, 20, 20]]), frame([[300, 300, 320, 320]]), np.eye(3), Config())
        self.assertEqual(result['matches'], [])

    def test_outside_image_and_empty_detections(self):
        h = np.array([[1., 0, -50], [0, 1, 0], [0, 0, 1]])
        self.assertEqual(associate(frame([[0, 0, 20, 20]]), frame([[0, 0, 20, 20]]), h, Config())['matches'], [])
        self.assertEqual(associate(frame([]), frame([]), np.eye(3), Config())['matches'], [])


class TrackTests(unittest.TestCase):
    def test_three_photos_merge_clipped_full_and_clipped_into_one_cow(self):
        frames = [frame([[0, 100, 20, 120]]), frame([[100, 100, 200, 120]]),
                  frame([[580, 100, 600, 120]])]
        records = [{'id': ident, 'observations': (f['boxes'] / [600, 400, 600, 400]).tolist()}
                   for ident, f in zip('abc', frames)]
        ab = np.array([[1., 0, 180], [0, 1, 0], [0, 0, 1]])
        bc = np.array([[1., 0, 480], [0, 1, 0], [0, 0, 1]])
        pairs = []
        for a, b, h in [(0, 1, ab), (1, 2, bc)]:
            result = associate(frames[a], frames[b], h, Config())
            pairs.append({'a': records[a]['id'], 'b': records[b]['id'],
                          'registration': {'accepted': True}, 'association': result})
        tracks = build_tracks(records, pairs)
        edges = summarize_track_edges(records, tracks['tracks'], Config())
        self.assertEqual(tracks['raw_observations'], 3)
        self.assertEqual(tracks['estimated_unique_observed'], 1)
        self.assertEqual(edges['clipped_resolved_in_other_photo'], 2)
        self.assertEqual(edges['recapture_targets'], [])

    def test_clipped_sighting_resolved_by_existing_full_view(self):
        records = [{'id': 'a', 'observations': [[0, .2, .01, .23]]},
                   {'id': 'b', 'observations': [[.5, .2, .55, .23]]}]
        result = build_tracks(records, [pair('a', 'b', [(0, 0, .1)])])
        edges = summarize_track_edges(records, result['tracks'], Config())
        self.assertEqual(result['estimated_unique_observed'], 1)
        self.assertEqual(edges['clipped_resolved_in_other_photo'], 1)
        self.assertEqual(edges['recapture_targets'], [])
        self.assertEqual(edges['preferred_observations'][0]['observation'], ['b', 0])

    def test_unresolved_clipped_cow_is_retained_and_requests_recapture(self):
        records = [{'id': 'a', 'observations': [[0, .2, .01, .23], [.99, .9, 1, 1]]}]
        result = build_tracks(records, [])
        edges = summarize_track_edges(records, result['tracks'], Config())
        self.assertEqual(result['estimated_unique_observed'], 2)
        self.assertEqual(edges['unresolved_clipped_tracks'], 2)
        self.assertEqual(edges['count_status'], 'needs_edge_recapture')
        self.assertEqual(edges['recapture_targets'][1]['image_edges'], ['right', 'bottom'])

    def test_merging_two_clipped_views_does_not_claim_full_view(self):
        records = [{'id': 'a', 'observations': [[0, .2, .01, .23]]},
                   {'id': 'b', 'observations': [[.99, .2, 1, .23]]}]
        result = build_tracks(records, [pair('a', 'b', [(0, 0, .1)])])
        edges = summarize_track_edges(records, result['tracks'], Config())
        self.assertEqual(edges['unresolved_clipped_tracks'], 1)
        self.assertEqual(edges['clipped_resolved_in_other_photo'], 0)

    def test_transitive_duplicate_is_counted_once(self):
        records = [record(c, '2023-01-01T12:00:00') for c in 'abc']
        result = build_tracks(records, [pair('a', 'b', [(0, 0, .1)]), pair('b', 'c', [(0, 0, .2)]), pair('a', 'c', [(0, 0, .3)])])
        self.assertEqual(result['estimated_unique_observed'], 1)
        self.assertEqual(result['deduplication_merges'], 2)

    def test_cycle_cannot_merge_two_cows_from_one_image(self):
        records = [record('a', '2023-01-01T12:00:00', count=2)] + [record(c, '2023-01-01T12:00:00') for c in 'bc']
        result = build_tracks(records, [pair('a', 'b', [(0, 0, .1)]), pair('b', 'c', [(0, 0, .2)]), pair('a', 'c', [(1, 0, .3)])])
        self.assertEqual(result['estimated_unique_observed'], 2)
        self.assertEqual(len(result['conflicting_associations']), 1)
        for track in result['tracks']:
            self.assertEqual(len(track), len({obs[0] for obs in track}))

    def test_missing_registration_retains_separate_observations(self):
        records = [record(c, '2023-01-01T12:00:00') for c in 'ab']
        result = build_tracks(records, [])
        self.assertEqual(result['estimated_unique_observed'], 2)


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(5)
        self.points = rng.uniform([20, 20], [480, 370], (100, 2)).astype(np.float32)
        self.descriptors = rng.random((100, 128)).astype(np.float32)

    def make_features(self, points):
        return {**frame([]), 'points': points, 'descriptors': self.descriptors}

    def test_known_homography_recovered(self):
        h = np.array([[1., .02, 35], [-.01, 1., 7], [.00001, .00002, 1.]])
        a, b = self.make_features(self.points), self.make_features(transform(self.points, h).astype(np.float32))
        result = register(a, b, Config())
        self.assertTrue(result['accepted'], result)
        np.testing.assert_allclose(transform(self.points, np.array(result['homography_a_to_b'])), b['points'], atol=.01)

    def test_nonoverlapping_footprints_rejected(self):
        result = register(self.make_features(self.points), self.make_features(self.points + [1000, 0]), Config())
        self.assertFalse(result['accepted'])

    def test_matches_in_single_small_patch_rejected(self):
        tiny = self.points * .05
        result = register(self.make_features(tiny), self.make_features(tiny + [50, 0]), Config())
        self.assertFalse(result['accepted'])

    def test_featureless_images_rejected(self):
        a = {**frame([]), 'points': np.empty((0, 2)), 'descriptors': None}
        self.assertFalse(register(a, a, Config())['accepted'])

    def test_clipping_on_coincident_and_almost_parallel_boundaries(self):
        small = box_polygon([0, 0, 20, 30])
        for dy in (-.0001, 0, .0001):
            large = np.float32([[0, 0], [600, dy], [600, 500], [0, 500]])
            for a, b in [(small, large), (large, small), (small[::-1], large[::-1])]:
                intersection = polygon_intersection(a, b)
                self.assertAlmostEqual(cv2.contourArea(intersection), 600, delta=.01)

    def test_clipping_intersection_never_exceeds_either_input(self):
        rng = np.random.default_rng(82)
        a = box_polygon([0, 0, 600, 500])
        for _ in range(100):
            start = rng.uniform([-50, -50], [650, 550])
            b = box_polygon([*start, *(start + rng.uniform(1, 100, 2))])
            ab, ba = polygon_intersection(a, b), polygon_intersection(b, a)
            area_ab = cv2.contourArea(ab) if len(ab) else 0
            area_ba = cv2.contourArea(ba) if len(ba) else 0
            self.assertLessEqual(area_ab, min(cv2.contourArea(a), cv2.contourArea(b)) + .01)
            self.assertAlmostEqual(area_ab, area_ba, delta=.01)


class InputTests(unittest.TestCase):
    def test_candidate_boundaries(self):
        a = record('a', '2023-01-01T23:59:59')
        b = record('b', '2023-01-02T00:00:00')
        self.assertEqual(list(candidate_pairs([a, b], Config())), [])
        b['meta']['captured'] = '2023-01-01T23:59:58'
        self.assertEqual(len(list(candidate_pairs([a, b], Config()))), 1)
        b['flight'] = 'other'
        self.assertEqual(list(candidate_pairs([a, b], Config())), [])
        b['flight'] = 'flight'
        b['meta']['captured'] = '2023-01-01T23:58:00'
        self.assertEqual(list(candidate_pairs([a, b], Config())), [])
        b['meta']['captured'] = '2023-01-01T23:59:58'
        b['meta']['lon'] += 1
        self.assertEqual(list(candidate_pairs([a, b], Config())), [])

    def test_no_prediction_fallback_to_labels(self):
        rec = {'id': 'a', 'image_sha256': 'expected', 'boxes': [[.1, .1, .2, .2]]}
        selection = {'selected_mode': 'model', 'selected_threshold': .5}
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                observations(rec, Path(tmp), selection)
            p = Path(tmp) / 'a.json'
            payload = {'id': 'a', 'image_sha256': 'wrong', 'modes': {'model': {'boxes': []}}}
            p.write_text(json.dumps(payload))
            with self.assertRaises(ValueError):
                observations(rec, Path(tmp), selection)
            payload['image_sha256'] = 'expected'
            payload['modes']['model']['boxes'] = [[.1, .1, .2, .2, .4], [.3, .3, .4, .4, .7]]
            p.write_text(json.dumps(payload))
            self.assertEqual(observations(rec, Path(tmp), selection), [[.3, .3, .4, .4]])

    def test_invalid_boxes_and_rounding(self):
        self.assertEqual(validate_boxes([[-.0000005, .1, .2, .2]])[0][0], 0)
        for box in ([.2, .1, .1, .2], [0, 0, float('nan'), 1], [-.1, 0, 1, 1]):
            with self.assertRaises(ValueError):
                validate_boxes([box])

    def test_edge_recapture_is_image_relative(self):
        self.assertEqual(edge_flags([[0, .2, .1, .3], [.5, .5, .6, .6], [.9, .9, 1, 1]]),
                         [{'detection': 0, 'image_edges': ['left']}, {'detection': 2, 'image_edges': ['right', 'bottom']}])


if __name__ == '__main__':
    unittest.main()
