"""Pipeline contract tests with real registration and a controlled detector boundary."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from training import count
from training.common import digest, read_json, write_json


class SurveyPipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.photos, self.output, self.predictions = (self.root / n for n in ('photos', 'output', 'predictions'))
        self.photos.mkdir()
        pixels = np.random.default_rng(7).integers(0, 256, (400, 600, 3), dtype=np.uint8)
        for ident in ('a', 'b'):
            Image.fromarray(pixels).save(self.photos / (ident + '.jpg'), quality=95)
        self.meta_patch = patch('scripts.aerial_survey.metadata', side_effect=self.metadata)
        self.meta_patch.start()
        self.addCleanup(self.meta_patch.stop)
        self.addCleanup(self.tmp.cleanup)

    def metadata(self, path):
        return dict(width=600, height=400, lat=46., lon=4., camera='fixture',
                    captured='2023-01-01T12:00:0' + ('0' if Path(path).stem == 'a' else '2'))

    def save_predictions(self, records, output=None, boxes=None):
        output = output or self.predictions
        output.mkdir(parents=True, exist_ok=True)
        for r in records:
            write_json(output / (r['id'] + '.json'), dict(id=r['id'], image_sha256=r['image_sha256'],
                       modes={'fixture': {'boxes': boxes if boxes is not None else [[.25, .3, .35, .4, .95]]}}))
        write_json(output / 'report.json', {'selection': {'selected_mode': 'fixture', 'selected_threshold': .5}})

    def run_pipeline(self, *extra):
        with contextlib.redirect_stdout(io.StringIO()):
            return count.main(['--data', str(self.photos), '--output', str(self.output), '--evidence-pairs', '0', *extra])

    def test_detector_then_overlap_produces_one_count_for_two_sightings(self):
        def detector(argv):
            inputs = Path(argv[argv.index('--data') + 1])
            output = Path(argv[argv.index('--output') + 1])
            records = read_json(inputs / 'manifest.json')['records']
            self.assertTrue(all('boxes' not in r for r in records))
            self.save_predictions(records, output)
        with patch('training.count.infer.main', side_effect=detector) as inference:
            result = self.run_pipeline()
        inference.assert_called_once()
        self.assertEqual(result['estimated_unique_observed'], 1)
        self.assertEqual(result['surveys'][0]['raw_observations'], 2)
        self.assertEqual(result['surveys'][0]['repeated_observations_removed'], 1)
        self.assertEqual(result['surveys'][0]['verified_overlap_pairs'], 1)
        self.assertTrue((self.output / 'result.json').exists())

    def test_saved_predictions_skip_detector_and_preserve_clipped_status(self):
        records = count.prepare_inputs(self.photos)['records']
        self.save_predictions(records, boxes=[[0, .2, .04, .3, .9]])
        with patch('training.count.infer.main', side_effect=AssertionError('Inference must be skipped')):
            result = self.run_pipeline('--predictions', str(self.predictions))
        self.assertEqual(result['estimated_unique_observed'], 1)
        self.assertEqual(result['status'], 'needs_edge_recapture')
        self.assertEqual(result['surveys'][0]['unresolved_clipped_tracks'], 1)

    def test_manifest_annotations_are_not_forwarded_and_original_flights_are_preserved(self):
        records = [dict(id=i, image=i + '.jpg', image_sha256=digest(self.photos / (i + '.jpg')),
                        flight='flight-' + i, boxes='must never be used') for i in ('a', 'b')]
        write_json(self.photos / 'manifest.json', {'records': records})
        prepared = count.prepare_inputs(self.photos)
        self.assertEqual({r['source_flight'] for r in prepared['records']}, {'flight-a', 'flight-b'})
        self.assertTrue(all('boxes' not in r for r in prepared['records']))
        self.assertFalse(prepared['annotations_used'])
        self.save_predictions(prepared['records'])
        result = self.run_pipeline('--predictions', str(self.predictions))
        self.assertEqual(len(result['surveys']), 2)
        self.assertIsNone(result['estimated_unique_observed'])
        self.assertTrue(all(r['estimated_unique_observed'] == 1 for r in result['surveys']))
        with self.assertRaisesRegex(ValueError, 'manifest flight assignments'):
            count.prepare_inputs(self.photos, flight_id='combine')

    def test_capture_dates_remain_separate_surveys(self):
        original = self.metadata
        def metadata(path):
            result = original(path)
            if Path(path).stem == 'b':
                result['captured'] = '2023-01-02T12:00:02'
            return result
        with patch('scripts.aerial_survey.metadata', side_effect=metadata):
            self.save_predictions(count.prepare_inputs(self.photos)['records'])
            result = self.run_pipeline('--predictions', str(self.predictions))
        self.assertEqual(len(result['surveys']), 2)
        self.assertIsNone(result['estimated_unique_observed'])

    def test_missing_prediction_stops_before_publishing_result(self):
        records = count.prepare_inputs(self.photos)['records']
        self.save_predictions(records[:1])
        with self.assertRaises(FileNotFoundError):
            self.run_pipeline('--predictions', str(self.predictions))
        self.assertFalse((self.output / 'result.json').exists())

    def test_missing_metadata_stops_before_inference(self):
        with patch('scripts.aerial_survey.metadata', side_effect=KeyError('GPS')), patch('training.count.infer.main') as inference:
            with self.assertRaisesRegex(ValueError, 'GPS/capture metadata'):
                self.run_pipeline()
            inference.assert_not_called()

    def test_inference_failure_does_not_publish_final_count(self):
        with patch('training.count.infer.main', side_effect=RuntimeError('detector failed')):
            with self.assertRaisesRegex(RuntimeError, 'detector failed'):
                self.run_pipeline()
        self.assertFalse((self.output / 'result.json').exists())

    def test_rerun_cannot_mix_changed_prediction_settings(self):
        self.save_predictions(count.prepare_inputs(self.photos)['records'])
        self.run_pipeline('--predictions', str(self.predictions))
        old_result = (self.output / 'result.json').read_bytes()
        report = read_json(self.predictions / 'report.json')
        report['selection']['selected_threshold'] = .8
        write_json(self.predictions / 'report.json', report)
        with self.assertRaisesRegex(ValueError, 'inputs/settings changed'):
            self.run_pipeline('--predictions', str(self.predictions))
        self.assertEqual(old_result, (self.output / 'result.json').read_bytes())

    def test_login_node_is_rejected_before_data_loading(self):
        with patch('socket.getfqdn', return_value='login001.oscar.ccv.brown.edu'), patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, 'login node'):
                self.run_pipeline()
        self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
