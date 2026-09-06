"""Count a drone survey: selected detector -> overlap matching -> distinct sightings.

    python -m training.count --data /path/to/photos --output /path/to/count --device cpu
    python -m training.count --data /path/to/photos --predictions /path/to/saved-run --output /path/to/count

Accepts an original photo, a photo directory, or a directory with manifest.json.
Plain folders represent one flight (override with --flight-id). Capture dates
remain separate surveys. GPS and capture time are required; annotations are never
used. On Oscar, execute inside a SLURM allocation, including saved-prediction runs.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts import aerial_survey
from training import infer
from training.common import digest, exclusive_lock, read_json, require_compute_job, write_json


def prepare_inputs(data, flight_id=None, image_ids=None):
    """Preserve original pixels and flight boundaries; never forward annotations."""
    require_compute_job()
    data = Path(data).resolve()
    source_manifest = data / 'manifest.json'
    manifest = read_json(source_manifest) if source_manifest.is_file() else None
    if manifest and flight_id is not None:
        raise ValueError('--flight-id is for plain photo inputs; manifest flight assignments are preserved')
    source_by_id = {r['id']: r for r in manifest['records']} if manifest else {}
    records = []
    for item in infer.input_records(data, image_ids):
        path = item['path'].resolve()
        image_sha = digest(path)
        if item['expected_sha256'] is not None and item['expected_sha256'] != image_sha:
            raise ValueError(f"Input image hash mismatch: {item['id']}")
        flight = source_by_id[item['id']].get('flight') if manifest else flight_id or data.stem
        if not isinstance(flight, str) or not flight.strip():
            raise ValueError(f"Missing flight assignment: {item['id']}")
        try:
            meta = aerial_survey.metadata(path)
        except (KeyError, ValueError, TypeError, ZeroDivisionError) as exc:
            raise ValueError(f"GPS/capture metadata required for {item['id']}: {exc}") from exc
        # A flight folder can contain images from more than one day. Do not add
        # those repeated visits together and present them as one herd inventory.
        records.append(dict(id=item['id'], image=str(path), image_sha256=image_sha,
                            flight=f"{flight} / {meta['captured'][:10]}",
                            source_flight=flight, capture_date=meta['captured'][:10]))
    return {'schema': 1, 'input_source': str(data), 'annotations_used': False, 'records': records}


def summarize(report, output, predictions):
    surveys = []
    for name, flight in report['flights'].items():
        surveys.append(dict(survey=name, images=flight['images'],
                            raw_observations=flight['raw_observations'],
                            repeated_observations_removed=flight['deduplication_merges'],
                            estimated_unique_observed=flight['estimated_unique_observed'],
                            verified_overlap_pairs=flight['verified_overlap_pairs'],
                            unresolved_clipped_tracks=flight['unresolved_clipped_tracks'],
                            status=flight['count_status']))
    return dict(schema=1, status='needs_edge_recapture' if any(s['unresolved_clipped_tracks'] for s in surveys) else 'proposed',
                source='model_predictions', detector_selection=report['detector_selection'],
                estimated_unique_observed=surveys[0]['estimated_unique_observed'] if len(surveys) == 1 else None,
                surveys=surveys, processed_images=report['summary']['processed_images'],
                coverage_verified=False,
                limitations=['Estimated distinct sightings; detection and association errors remain possible.',
                             'Sparse photographs do not verify complete property coverage.',
                             'Different flights and capture dates are reported separately, never summed as one herd.'],
                artifacts={'input_manifest': str(output / 'inputs/manifest.json'),
                           'predictions': str(predictions), 'overlap_report': str(output / 'overlap/report.json')})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--data', '--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--predictions', type=Path, help='Reuse an existing detector run and skip model inference')
    parser.add_argument('--weights', type=Path, help='Location of the selected, SHA-pinned checkpoint')
    parser.add_argument('--device', default='cpu')
    parser.add_argument('--flight-id', help='Flight name for plain photo inputs; manifest flights remain separate')
    parser.add_argument('--image-ids', nargs='+', help='Optional explicit subset of input image IDs')
    parser.add_argument('--max-seconds', type=float, default=30)
    parser.add_argument('--max-distance-m', type=float, default=160)
    parser.add_argument('--evidence-pairs', type=int, default=6)
    args = parser.parse_args(argv)
    if args.predictions and args.weights:
        parser.error('--weights cannot be used with --predictions')
    if args.max_seconds <= 0 or args.max_distance_m <= 0 or args.evidence_pairs < 0:
        parser.error('Time/distance must be positive and evidence count nonnegative')
    require_compute_job()
    manifest = prepare_inputs(args.data, args.flight_id, args.image_ids)
    output = args.output.resolve()
    predictions = args.predictions.resolve() if args.predictions else output / 'detections'
    if args.predictions:
        selection = read_json(predictions / 'report.json')['selection']
        # Fail before creating the run if any photo lacks usable predictions.
        for record in manifest['records']:
            aerial_survey.observations(record, predictions, selection)
    protocol = dict(schema=1, inputs=manifest, device=None if args.predictions else args.device,
                    detector_config=infer.load_default_config() if not args.predictions else None,
                    saved_predictions=str(predictions) if args.predictions else None,
                    saved_prediction_hashes={r['id']: digest(predictions / (r['id'] + '.json')) for r in manifest['records']} if args.predictions else None,
                    saved_report_sha256=digest(predictions / 'report.json') if args.predictions else None,
                    max_seconds=args.max_seconds, max_distance_m=args.max_distance_m, evidence_pairs=args.evidence_pairs,
                    count_code_sha256=digest(Path(__file__)), overlap_code_sha256=digest(Path(aerial_survey.__file__)),
                    inference_code_sha256=digest(Path(infer.__file__)) if not args.predictions else None)
    with exclusive_lock(output / '.pipeline.lock'):
        protocol_path = output / 'pipeline.json'
        if protocol_path.exists() and read_json(protocol_path) != protocol:
            raise ValueError('Pipeline inputs/settings changed; choose a new output directory')
        inputs = output / 'inputs'
        inputs.mkdir(parents=True, exist_ok=True)
        write_json(protocol_path, protocol)
        write_json(inputs / 'manifest.json', manifest)
        if not args.predictions:
            print('Stage 1/2: detect cows with the selected model', flush=True)
            infer_args = ['--data', str(inputs), '--output', str(predictions), '--device', args.device]
            if args.weights:
                infer_args += ['--weights', str(args.weights)]
            infer.main(infer_args)
        else:
            print('Stage 1/2: reuse saved model detections', flush=True)
        print('Stage 2/2: align photos and merge repeated cow sightings', flush=True)
        report = aerial_survey.main(['--data', str(inputs), '--run', str(predictions), '--output', str(output / 'overlap'),
                                    '--max-seconds', str(args.max_seconds), '--max-distance-m', str(args.max_distance_m),
                                    '--evidence-pairs', str(args.evidence_pairs)])
        if report['quarantined'] or report['summary']['processed_images'] != len(manifest['records']):
            raise ValueError('Survey did not process every selected photo; inspect overlap/report.json')
        result = summarize(report, output, predictions)
        write_json(output / 'result.json', result)
        print(json.dumps({'result': str(output / 'result.json'), 'surveys': result['surveys']}, indent=2), flush=True)
        return result


if __name__ == '__main__':
    main()
