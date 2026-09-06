"""Small integration check on original, separate drone photographs.

Positive links were inspected in validation/overlap/edge-validation/real-edge-matches.jpg.
This is a regression fixture, not a claim of complete cross-photo ground truth.
"""
import json
from pathlib import Path
import unittest

import cv2
import numpy as np

from aerial_survey import Config, prepare, register, associate, sha256


DATA = Path(__file__).resolve().parents[1] / 'validation' / 'data'


@unittest.skipUnless((DATA / 'manifest.json').exists(), 'Original local validation images required')
class RealEdgeTests(unittest.TestCase):
    def test_visually_reviewed_edge_cows_in_separate_photos(self):
        manifest = {r['id']: r for r in json.loads((DATA / 'manifest.json').read_text())['records']}
        fixtures = [('f70fffcefcbc', 'e08d9c27bd62', 21, 28),
                    ('afec265ae16c', '7b15fd5b53c9', 42, 49)]
        cv2.setNumThreads(2)
        for a_id, b_id, ai, bi in fixtures:
            with self.subTest(a=a_id, b=b_id):
                frames = []
                for ident in (a_id, b_id):
                    record = manifest[ident]
                    self.assertEqual(sha256(DATA / record['image']), record['image_sha256'])
                    frames.append(prepare(DATA / record['image'], record['boxes'], Config()))
                registration = register(*frames, Config())
                self.assertTrue(registration['accepted'], registration)
                result = associate(*frames, np.asarray(registration['homography_a_to_b']), Config())
                matches = [m for m in result['matches'] if m['a'] == ai]
                self.assertEqual([m['b'] for m in matches], [bi])
                self.assertEqual(matches[0]['method'], 'shared_edge_region')


if __name__ == '__main__':
    unittest.main()
