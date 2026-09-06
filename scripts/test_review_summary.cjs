const {test} = require('node:test');
const assert = require('node:assert/strict');
const {buildHerdProofReviewSummary: summarize} = require('./survey/web/review-summary.js');

function fixture() {
  const parcel = {id:'field-a',name:'North field',sha256:'boundary-a'};
  const report = {id:'report-a',parcel,filename:'first.jpg',declared_capture_date:'2023-09-26',
    media:{byte_sha256:'photo-a',captured_local:'2023-09-26T13:00:00'},
    checks:[{code:'capture_date',status:'PASS'},{code:'coverage',status:'NOT TESTED'}]};
  const batch = {id:'batch-a',photos:[{meta:{byte_sha256:'photo-a',captured_local:'2023-09-26T13:00:00'}},
    {meta:{byte_sha256:'photo-b',captured_local:'2023-09-26T13:00:05'}}]};
  const world = {id:'world-a',status:'ready',batch_id:batch.id,parcel_id:parcel.id,url:'/worlds/world-a/',
    result:{cows:18,merged_sightings:12,boundary_review:1,appearance_review:2,placement_review:0,outside_boundary:4,coverage_percent:91}};
  return {parcel,report,batch,world,model:{image_sha256:'photo-a',count:22}};
}
const card = (summary,label) => summary.cards.find(item => item.label === label);

test('a matching world reports display counts, pending observations and a concrete action', () => {
  const result = summarize(fixture());
  assert.equal(card(result,'Cow observations').value,'18 displayed');
  assert.equal(card(result,'Observation review').value,'3 pending');
  assert.equal(card(result,'Repeated cow sightings').value,'12 merged');
  assert.equal(result.state,'Needs review');
  assert.match(result.nextAction,/another view/);
  assert.match(result.nextAction,/uncovered area/);
});

test('a different boundary cannot inherit the last displayed assessment or world', () => {
  const input = fixture();input.parcel={id:'field-b',name:'Other field',sha256:'boundary-b'};
  const result=summarize(input);
  assert.equal(card(result,'Cow observations').value,'Not available');
  assert.equal(card(result,'Estimated photo coverage').value,'Unknown');
  assert.equal(result.reportId,null);assert.equal(result.worldUrl,null);
});

test('an unrelated photo or a changed declared date cannot borrow world results', () => {
  for(const change of [input=>input.report.media.byte_sha256='other-photo', input=>input.report.declared_capture_date='2023-09-27']) {
    const input=fixture();change(input);const result=summarize(input);
    assert.equal(result.worldUrl,null);
    assert.equal(card(result,'Estimated photo coverage').value,'Unknown');
    assert.equal(card(result,'Repeated cow sightings').value,'Not assessed');
  }
});

test('single-photo detector candidates require the exact image hash and retain their scope', () => {
  const input=fixture();input.world=null;
  let result=summarize(input);
  assert.equal(card(result,'Cow observations').value,'22 candidates');
  assert.match(card(result,'Cow observations').detail,/not a parcel total/);
  input.model.image_sha256='different-file';result=summarize(input);
  assert.equal(card(result,'Cow observations').value,'Not available');
});

test('an old coverage response must match the batch, boundary ID and boundary hash', () => {
  const input=fixture();input.world=null;
  input.coverage={batch_id:'batch-a',parcel_id:'field-a',boundary_sha256:'boundary-a',percent:0};
  assert.equal(card(summarize(input),'Estimated photo coverage').value,'0%');
  for(const key of ['batch_id','parcel_id','boundary_sha256']) {
    const changed=structuredClone(input);changed.coverage[key]='old';
    assert.equal(card(summarize(changed),'Estimated photo coverage').value,'Unknown');
  }
});

test('file reuse flags are distinct from cow matching and never establish fraud', () => {
  const input=fixture();input.world=null;
  input.report.checks.push({code:'exact_reuse',status:'FAIL'},{code:'pixel_reuse',status:'FAIL'});
  const result=summarize(input);
  assert.match(card(result,'Photo evidence checks').detail,/1 photo flagged for reuse/);
  assert.equal(card(result,'Repeated cow sightings').value,'Not assessed');
  assert.match(result.nextAction,/reuse alone does not establish fraud/);
});

test('batch checks count each photo once, include conflicts and retain untested findings', () => {
  const input=fixture();input.world=null;
  const second={...input.report,id:'report-b',media:{byte_sha256:'photo-b'},checks:[{code:'capture_date',status:'FAIL'}]};
  input.batchRun={batch_id:input.batch.id,parcel_id:input.parcel.id,date:input.report.declared_capture_date,reports:[input.report,second]};
  const result=summarize(input);
  assert.equal(card(result,'Photo evidence checks').value,'1 conflict');
  assert.match(card(result,'Photo evidence checks').detail,/2 of 2 photos checked; 1 inconclusive or untested/);
});

test('missing metadata and consistent checks never become verified inventory or approval', () => {
  const input=fixture();input.world=null;input.batch=null;input.report.media.captured_local=null;
  const result=summarize(input);
  assert.match(card(result,'Capture date').detail,/unknown/);
  assert.equal(card(result,'Estimated photo coverage').value,'Unknown');
  assert.equal(result.state,'Human review required');
  assert.equal(summarize().state,'Awaiting evidence');
});
