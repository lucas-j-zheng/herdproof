'use strict';

// Keep summaries tied to the evidence scope, never to the last result on screen.
function buildHerdProofReviewSummary({parcel = null, report = null, model = null,
  batch = null, world = null, coverage = null, batchRun = null} = {}) {
  if (!parcel || report?.parcel?.id !== parcel.id) report = null;
  const photos = batch?.photos || [];
  const hashes = new Set(photos.map(photo => photo.meta.byte_sha256));
  const reportInBatch = !!report && hashes.has(report.media.byte_sha256);
  const dates = [...new Set(photos.map(photo => photo.meta.captured_local?.slice(0, 10) || 'Unknown'))];
  const matchingDate = !report || (dates.length === 1 && dates[0] === report.declared_capture_date);
  const matchingBatch = !!parcel && !!batch && (!report || reportInBatch) && matchingDate;
  const matchingWorld = matchingBatch && world?.status === 'ready' &&
    world.batch_id === batch.id && world.parcel_id === parcel.id ? world : null;
  const result = matchingWorld?.result;
  const matchingCoverage = matchingBatch && coverage?.batch_id === batch.id &&
    coverage.parcel_id === parcel.id && coverage.boundary_sha256 === parcel.sha256 ? coverage : null;
  const singleModel = report && model?.image_sha256 === report.media.byte_sha256 ? model : null;

  let reports = report ? [report] : [];
  if (matchingBatch && batchRun?.batch_id === batch.id && batchRun.parcel_id === parcel.id &&
      batchRun.date === report?.declared_capture_date) {
    reports = [...new Map([...batchRun.reports, report].filter(item => item &&
      item.parcel.id === parcel.id && item.declared_capture_date === report.declared_capture_date &&
      hashes.has(item.media.byte_sha256)).map(item => [item.media.byte_sha256, item])).values()];
  }
  const checks = reports.flatMap(item => item.checks);
  const conflicts = checks.filter(check => check.status === 'FAIL');
  const unresolved = checks.filter(check => !['PASS', 'FAIL'].includes(check.status));
  const reused = reports.filter(item => item.checks.some(check =>
    ['exact_reuse', 'pixel_reuse'].includes(check.code) && check.status === 'FAIL')).length;
  const pending = result ? (result.boundary_review || 0) + (result.appearance_review || 0) + (result.placement_review || 0) : null;
  const footprint = result?.coverage_percent ?? matchingCoverage?.percent;
  const checkedTotal = matchingBatch ? photos.length : report ? 1 : photos.length;
  const date = report?.declared_capture_date || (matchingBatch && dates.length === 1 ? dates[0] : dates.length > 1 ? 'Mixed dates' : 'Not supplied');
  const cards = [
    {label: 'Cow observations', value: result ? `${result.cows} displayed` : singleModel ? `${singleModel.count} candidates` : 'Not available',
      detail: result ? 'Automatic world draft. Pending and outside-boundary observations are excluded from this display count.' :
        singleModel ? 'Saved detector output for this exact photo; unreviewed and not a parcel total.' : 'Build a field world to run detection on supported survey photos.'},
    {label: 'Capture date', value: date,
      detail: report ? `Photo EXIF: ${report.media.captured_local?.slice(0, 10) || 'unknown'}. The declared date and camera metadata are assertions.` : 'Camera-local dates; missing metadata stays unknown.'},
    {label: 'Estimated photo coverage', value: Number.isFinite(footprint) ? `${footprint}%` : 'Unknown',
      detail: 'Boundary area under approximate photo footprints. A full-property sweep remains unverified.'},
    {label: 'Photo evidence checks', value: reports.length ? `${conflicts.length} conflict${conflicts.length === 1 ? '' : 's'}` : 'Not checked',
      detail: reports.length ? `${reports.length} of ${checkedTotal} photos checked; ${unresolved.length} inconclusive or untested finding${unresolved.length === 1 ? '' : 's'}. ${reused} photo${reused === 1 ? '' : 's'} flagged for reuse.` : 'Check the photos for reuse and date or location conflicts.'},
    {label: 'Repeated cow sightings', value: result ? `${result.merged_sightings} merged` : 'Not assessed',
      detail: result ? 'Automatic world-placement matches across these photos. Animal identity remains unverified.' : 'Cross-photo cow matching is separate from checking whether an uploaded file was reused.'},
    {label: 'Observation review', value: result ? `${pending} pending` : singleModel ? 'Unreviewed' : 'Not started',
      detail: result ? `${result.boundary_review || 0} edge, ${result.appearance_review || 0} appearance and ${result.placement_review || 0} placement findings. ${result.outside_boundary || 0} outside-boundary sightings.` : 'A person must check proposed observations and any missing views.'},
  ];

  const actions = [];
  if (!parcel || !photos.length && !report) actions.push('Load the demo batch or a survey and save a boundary.');
  if (conflicts.length) actions.push(`Review ${conflicts.length} photo conflict${conflicts.length === 1 ? '' : 's'} in the assessment below; reuse alone does not establish fraud.`);
  if (pending) actions.push(`Inspect ${pending} pending observation${pending === 1 ? '' : 's'} in the world review findings; request another view where an edge sighting cannot be resolved.`);
  if (Number.isFinite(footprint) && footprint < 100) actions.push('Inspect the uncovered area and request additional imagery if it is needed for this review.');
  if (parcel && (photos.length || report) && reports.length < checkedTotal) actions.push('Run the remaining photo checks against this boundary and declared date.');
  if (!actions.length) actions.push(reports.length ? 'Review the observations and remaining unknowns, then export the assessment for the existing lending review process.' : 'Check the survey photos, then inspect the proposed cattle observations.');
  const scope = report ? `${parcel.name} · ${matchingBatch ? `${photos.length}-photo survey; selected photo: ` : 'Selected photo: '}${report.filename}` :
    parcel && photos.length ? `${parcel.name} · ${photos.length} survey photos. No photo assessment selected.` :
    'Load survey photos and save a boundary to begin. Results here stay tied to the selected survey.';
  return {scope, cards, nextAction: actions.join(' '),
    state: conflicts.length || pending ? 'Needs review' : reports.length || result ? 'Human review required' : 'Awaiting evidence',
    reportId: report?.id || null, worldUrl: matchingWorld?.url || null};
}

if (typeof module !== 'undefined' && module.exports) module.exports = {buildHerdProofReviewSummary};
