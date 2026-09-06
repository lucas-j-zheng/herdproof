'use strict';
const $ = id => document.getElementById(id);
const svgNS = 'http://www.w3.org/2000/svg';
const STATUS_LABEL = {PASS:'Consistent', FAIL:'Conflict', INCONCLUSIVE:'Inconclusive', NOT_TESTED:'Not tested'};
let bootstrap, csrf, points = [], selected = null, mode = 'draw', view = [0, 0, 1000, 1000];
let source = null, encoded = null, filename = '', busy = false, activeReport = null, drag = null;
let previewURL = null, lastRequest = null, camera = null;
let batch = null, batchPhoto = null, batchRun = null, batchTimer = null, coverageVersion = 0;
let pointHistory = [];
let currentWorld = null, worldTimer = null, worldSubmitting = false;
let reviewCoverage = null;
const addVerticesButton = document.createElement('button');
addVerticesButton.id='add-vertices';addVerticesButton.textContent='Add vertices';addVerticesButton.disabled=true;
$('edit').after(addVerticesButton);
$('undo').textContent='Undo';

function node(tag, text, cls) { const el = document.createElement(tag); if (text != null) el.textContent = text; if (cls) el.className = cls; return el; }
function svg(tag, attrs) { const el = document.createElementNS(svgNS, tag); for (const [k,v] of Object.entries(attrs)) el.setAttribute(k, v); return el; }
function message(text, error = false) { $(error ? 'error' : 'notice').textContent = text; $(error ? 'error' : 'notice').hidden = !text; if (text) $(error ? 'notice' : 'error').hidden = true; }
async function api(path, data) {
  const response = await fetch('/api/survey/' + path, data === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json','X-Demo-Token':csrf}, body:JSON.stringify(data)});
  const result = await response.json(); if (!response.ok) throw Error(result.error || `Request failed (${response.status})`); return result;
}
function action(id, fn) { $(id).addEventListener('click', async () => { try { message(''); await fn(); } catch (e) { message(e.message, true); } }); }
function toMap([x,y]) { const [w,s,e,n] = bootstrap.map.bounds; return [(x-w)/(e-w)*1000, (n-y)/(n-s)*1000]; }
function toWorld([x,y]) { const [w,s,e,n] = bootstrap.map.bounds; return [w+x/1000*(e-w), n-y/1000*(n-s)]; }
function eventPoint(e) { const point = new DOMPoint(e.clientX,e.clientY).matrixTransform($('map').getScreenCTM().inverse()); return [point.x,point.y]; }
function setMode(next) { mode = next; $('draw').setAttribute('aria-pressed',mode==='draw'); $('edit').setAttribute('aria-pressed',mode==='edit'); $('map').style.cursor = mode==='draw' ? 'crosshair' : 'grab'; $('map-hint').textContent = mode==='draw' ? 'Click boundary corners. Choose Edit / pan to adjust the outline or add points along an edge.' : 'Drag white vertices to follow field edges. Click or drag a small + on an edge to add a vertex. Add vertices adds control points around the outline.'; if(bootstrap)renderMap(); }
function hideAssessment() { activeReport=null; $('assessment').hidden=true; $('record-empty').hidden=false; renderReviewSummary(); }
function dirty() { selected = null; $('saved-parcels').value=''; hideAssessment(); clearRetry(); clearBatchRun(); updateCoverage(); refreshState(); }
function rememberPoints() { pointHistory.push(points.map(p=>[...p])); if(pointHistory.length>50)pointHistory.shift(); }
function undoBoundary() { if(!pointHistory.length)return;points=pointHistory.pop();dirty();renderMap();renderVertices(); }
function midpoint(index) { const a=points[index],b=points[(index+1)%points.length];return [(a[0]+b[0])/2,(a[1]+b[1])/2]; }
function insertVertex(index) { if(busy || points.length<3 || points.length>=128)return null;const p=midpoint(index);rememberPoints();points.splice(index+1,0,p);dirty();return index+1; }
function refreshState() {
  refreshWorldButton();
  renderReviewSummary();
  $('map-intro').hidden = !!(points.length || batch || selected);
  $('boundary-state').textContent = selected ? 'Saved boundary' : points.length ? 'Unsaved outline' : 'Not saved';
  $('boundary-state').classList.toggle('saved',!!selected);
  $('area').textContent = selected ? `${selected.area_ha.toFixed(2)} hectares, ${points.length} vertices` : `${points.length} vertices, save to calculate area`;
  $('save').disabled = busy || points.length < 3; $('export-geojson').disabled = !selected;
  $('submit').disabled = busy || !selected || !source || !$('capture-date').value;
  $('submit').textContent = 'Check selected photo';
  $('check-batch').hidden = !batch?.photos.length;
  $('check-batch').disabled = busy || !selected || !batch?.photos.length || !$('capture-date').value;
  $('submission-hint').textContent = selected && source ? 'Each photo gets its own saved assessment against this boundary. Rechecking can flag prior use.' : 'Save a boundary and choose photos to run the checks.';
  for(const id of ['example-photo','example-batch','upload','capture-date','retry','retry-batch','example-boundary','parcel-name','saved-parcels','saved-batches','import-geojson','draw','edit','undo','clear','start-map','start-upload','build-batch']) $(id).disabled=busy;
  $('add-vertices').disabled = busy || points.length<3 || points.length>=128;
  $('undo').disabled = busy || !pointHistory.length;
  $('example-batch').disabled = busy || !bootstrap?.map.demo_batch?.length;
  document.querySelectorAll('.photo-tile,.vertex-row input,.vertex-row button,.history-row,.batch-results button').forEach(el=>el.disabled=busy);
}
function mapUnitsPerPixel() {
  const matrix = $('map').getScreenCTM();
  return matrix ? 1 / Math.hypot(matrix.a, matrix.b) : 1;
}
function renderMap() {
  $('map').setAttribute('viewBox', view.join(' '));
  const layer = $('boundary-layer');
  layer.replaceChildren();
  const unit = mapUnitsPerPixel();
  renderFootprints(unit);
  const outline = points.map(p => p.join(',')).join(' ');
  if (points.length >= 3) {
    // Dim the surroundings, so the actual selected ground remains easy to read.
    const [x,y,w,h] = view;
    const outside = `M${x},${y}h${w}v${h}h${-w}Z M${points.map(p=>p.join(',')).join(' L')}Z`;
    layer.append(svg('path', {d:outside, fill:'#0f1a19', 'fill-opacity':'.42', 'fill-rule':'evenodd', 'pointer-events':'none'}));
    layer.append(svg('polygon', {points:outline, fill:'#2fd6cf', 'fill-opacity':'.10', 'pointer-events':'none'}));
  }
  if (points.length) {
    const shape = points.length >= 3 ? 'polygon' : 'polyline';
    const edge = {points:outline, fill:'none', 'stroke-linejoin':'round', 'stroke-linecap':'round', 'vector-effect':'non-scaling-stroke', 'pointer-events':'none'};
    layer.append(svg(shape, {...edge, stroke:'#08302f', 'stroke-opacity':'.7', 'stroke-width':5}));
    layer.append(svg(shape, {...edge, stroke:'#54e2da', 'stroke-width':2.5}));
  }
  if(mode==='edit' && !busy && points.length>=3 && points.length<128)points.forEach((p,i)=>{
    const q=points[(i+1)%points.length];
    if(Math.hypot(p[0]-q[0],p[1]-q[1])<56*unit)return;
    const [x,y]=midpoint(i), handle=svg('g',{'data-insert-after':i,role:'button',tabindex:0,'aria-label':`Add vertex on edge ${i+1}`,cursor:'copy'});
    handle.append(svg('circle',{cx:x,cy:y,r:14*unit,fill:'transparent'}));
    handle.append(svg('circle',{cx:x,cy:y,r:6*unit,fill:'#17694d',stroke:'#d8ffe8','stroke-width':1.5,'vector-effect':'non-scaling-stroke'}));
    handle.append(svg('path',{d:`M${x-3*unit},${y}h${6*unit} M${x},${y-3*unit}v${6*unit}`,stroke:'#fff','stroke-width':1.5,'vector-effect':'non-scaling-stroke','pointer-events':'none'}));
    layer.append(handle);
  });
  points.forEach((p,i) => {
    // A generous invisible hit area keeps dragging usable without large visual dots.
    layer.append(svg('circle', {cx:p[0],cy:p[1],r:15*unit,fill:'transparent','data-index':i,cursor:'move'}));
    layer.append(svg('circle', {cx:p[0],cy:p[1],r:5*unit,fill:'#fff',stroke:'#0e6b6b','stroke-width':2,'vector-effect':'non-scaling-stroke','data-index':i,cursor:'move'}));
  });
  const marker = $('camera-layer');
  marker.replaceChildren();
  if (camera) {
    const p = toMap(camera);
    marker.append(svg('circle', {cx:p[0],cy:p[1],r:7*unit,fill:'#f4ae3e',stroke:'#fff','stroke-width':2,'vector-effect':'non-scaling-stroke'}));
    const label = svg('text', {x:p[0]+12*unit,y:p[1]-12*unit,fill:'#fff','font-size':13*unit,'font-weight':'700',stroke:'#12211f','stroke-width':3*unit,'paint-order':'stroke','pointer-events':'none'});
    label.textContent='Photo GPS';
    marker.append(label);
  }
}
function renderVertices() {
  $('vertices').replaceChildren(); points.forEach((point,i)=>{ const row=node('div',null,'vertex-row'); row.append(node('span',String(i+1))); const world=toWorld(point);
    ['Easting','Northing'].forEach((name,axis)=>{const input=node('input');input.type='number';input.step='.1';input.value=world[axis].toFixed(2);input.setAttribute('aria-label',`Vertex ${i+1} ${name}`); input.addEventListener('change',()=>{const value=Number(input.value);if(!input.value || !Number.isFinite(value)){message('Enter a finite coordinate.',true);return;}const next=toWorld(points[i]);next[axis]=value;rememberPoints();points[i]=toMap(next);dirty();renderMap();});row.append(input);});
    const remove=node('button','×');remove.setAttribute('aria-label',`Remove vertex ${i+1}`);remove.onclick=()=>{rememberPoints();points.splice(i,1);dirty();renderMap();renderVertices();};row.append(remove);$('vertices').append(row);
  });
}
function fit(target = null) {
  const rect = $('map').getBoundingClientRect();
  const aspect = rect.width / rect.height || 1;
  target = Array.isArray(target) ? target : points.length ? points : surveyPoints().length ? surveyPoints() : [[0,0],[1000,1000]];
  const xs = target.map(p=>p[0]), ys = target.map(p=>p[1]);
  const minx=Math.min(...xs), miny=Math.min(...ys), maxx=Math.max(...xs), maxy=Math.max(...ys);
  const height = Math.max(maxy-miny, (maxx-minx)/aspect, 80) * 1.35;
  const width = height * aspect;
  view = [(minx+maxx-width)/2, (miny+maxy-height)/2, width, height];
  renderMap();
}
function zoom(factor, centre=[view[0]+view[2]/2,view[1]+view[3]/2]) {
  const width = Math.max(30,Math.min(200000,view[2]*factor));
  const ratio = width/view[2];
  view = [centre[0]-(centre[0]-view[0])*ratio, centre[1]-(centre[1]-view[1])*ratio, width, view[3]*ratio];
  renderMap();
}
function savedOptions() { const select=$('saved-parcels');select.replaceChildren(new Option('Choose a boundary',''));for(const parcel of bootstrap.parcels)select.add(new Option(`${parcel.name} (${parcel.area_ha.toFixed(2)} ha)`,parcel.id));if(selected)select.value=selected.id; }
function useParcel(parcel) { hideAssessment();clearRetry();clearBatchRun();pointHistory=[];selected=parcel;points=parcel.map_vertices.map(toMap);$('parcel-name').value=parcel.name;setMode('edit');savedOptions();refreshState();renderVertices();fit();updateCoverage(); }
function download(url) { const a=node('a');a.href=url;a.download='';document.body.append(a);a.click();a.remove(); }
function showPhoto(url, caption) { $('photo').src=url;$('photo').hidden=false;$('photo-empty').hidden=true;$('photo-caption').textContent=caption; }
function showModel(hash) { const model=bootstrap.map.model;$('model-note').hidden=!model || model.image_sha256!==hash;if(!$('model-note').hidden)$('model-note').textContent=`Saved detector run: ${model.count} cattle candidates at confidence ${model.confidence}. These are unreviewed image observations, not a verified parcel total.`; }
function clearRetry() { lastRequest=null;$('retry').hidden=true; }

function showReport(report, scroll = true) {
  activeReport=report;$('assessment').hidden=false;
  const failures=report.checks.filter(c=>c.status==='FAIL').length;
  $('assessment-heading').textContent=failures ? `${failures} ${failures===1?'conflict':'conflicts'} to review` : 'No conflicts found in these checks';
  $('record-empty').hidden=true;
  $('record-file').textContent=report.filename;
  $('record-parcel').textContent=report.parcel.name;
  $('record-declared').textContent=report.declared_capture_date;
  $('checks').replaceChildren();
  for(const check of report.checks){const card=node('article',null,'check '+check.status);const body=node('div');const title=node('div',null,'check-title');title.append(node('h3',check.label),node('span',STATUS_LABEL[check.status]||check.status,'status '+check.status));body.append(title,node('p',check.message));if(Object.keys(check.evidence).length){const detail=node('details');detail.append(node('summary','View evidence'),node('pre',JSON.stringify(check.evidence,null,2)));body.append(detail);}const mark=node('span',null,'mark');mark.setAttribute('aria-hidden','true');card.append(mark,body);$('checks').append(card);}
  $('evidence-details').textContent=JSON.stringify({assessment_id:report.id,received_utc:report.received_utc,boundary_sha256:report.parcel.sha256,report_sha256:report.report_sha256,media:report.media},null,2);
  $('limits').replaceChildren(...report.limitations.map(x=>node('li',x)));
  camera=report.media.map_point;renderMap();showModel(report.media.byte_sha256);
  renderReviewSummary();
  if(scroll)$('assessment').scrollIntoView({behavior:'smooth',block:'start'});
}
function renderHistory() {
  $('history').replaceChildren();if(!bootstrap.reports.length){$('history').append(node('p','No evidence submitted yet.','hint'));return;}
  for(const report of bootstrap.reports){const button=node('button',null,'history-row');const text=node('span',report.filename);text.append(node('small',new Date(report.received_utc).toLocaleString()),node('small',report.id.slice(0,8)));button.append(text,node('span',report.status==='needs_review'?'Needs review':'No conflicts','status '+(report.status==='needs_review'?'FAIL':'PASS')));button.onclick=async()=>{try{const full=await api('reports/'+report.id);useParcel(full.parcel);showReport(full);message('Viewing a saved assessment. The evidence form remains a separate new submission.');}catch(e){message(e.message,true);}};$('history').append(button);}
}
async function refreshHistory(){const result=await api('bootstrap');bootstrap.reports=result.reports;renderHistory();}
async function sendSubmission(request) {
  try { const result=await api('submissions',request);clearRetry();useParcel(result.report.parcel);showReport(result.report);await refreshHistory();message(result.retry?'Recovered the original assessment; no extra submission was created.':'Assessment saved. Findings are based on the original uploaded bytes.'); }
  catch(e){$('retry').hidden=false;throw e;}
}

function surveyPoints() { return batch?.photos.flatMap(p=>p.placement.corners?.map(toMap) || []) || []; }
function renderFootprints(unit) {
  const layer = $('footprint-layer'); layer.replaceChildren();
  if (!batch || !$('show-imagery').checked) return;
  const coverage=batch.result?.coverage;
  if(coverage){
    const polygons=coverage.type==='Polygon'?[coverage.coordinates]:coverage.coordinates;
    const path=polygons.flatMap(p=>p.map(ring=>'M'+ring.map(toMap).map(p=>p.join(',')).join(' L')+'Z')).join(' ');
    layer.append(svg('path',{d:path,fill:'none',stroke:'#ffc45c','stroke-width':1.5,'stroke-dasharray':'6 4','vector-effect':'non-scaling-stroke'}));
  }
  for(const photo of batch.photos) {
    const corners=photo.placement.corners;
    if(corners && $('show-footprints').checked) {
      layer.append(svg('polygon',{points:corners.map(toMap).map(p=>p.join(',')).join(' '),fill:'none',stroke:'#ffc45c','stroke-width':photo.id===batchPhoto?2:1,'stroke-dasharray':photo.id===batchPhoto?'none':'5 4','vector-effect':'non-scaling-stroke'}));
    }
    if(!corners && photo.meta.map_point && photo.meta.gps?.latitude>=41 && photo.meta.gps?.latitude<=52 && photo.meta.gps?.longitude>=-5.5 && photo.meta.gps?.longitude<=10.5){
      const [x,y]=toMap(photo.meta.map_point);
      layer.append(svg('circle',{cx:x,cy:y,r:5*unit,fill:'#ffc45c',stroke:'#fff','stroke-width':1,'vector-effect':'non-scaling-stroke'}));
    }
  }
}
function renderSurveyImage() {
  const layer=$('survey-layer'); layer.replaceChildren();
  const bounds=batch?.result?.bounds;
  $('map-layers').hidden=!batch?.photos.length;
  $('placement-note').hidden=!bounds;
  $('placement-note').textContent=bounds?'Approximate photo map from camera metadata and overlapping background matches. Flat-ground placement can shift field edges, so check the alignment.':'';
  if(bounds){
    const [w,s,e,n]=bounds, top=toMap([w,n]), bottom=toMap([e,s]);
    layer.append(svg('image',{href:`/api/survey/batches/${batch.id}/mosaic.png`,x:top[0],y:top[1],width:bottom[0]-top[0],height:bottom[1]-top[1],preserveAspectRatio:'none'}));
  }
  layer.style.display=$('show-imagery').checked?'':'none'; renderMap();
}
function chooseBatchPhoto(photo, setDate = true) {
  if(busy)return;
  hideAssessment();clearRetry();batchPhoto=photo.id;source='batch';encoded=null;filename=photo.filename;
  camera=photo.meta.map_point;
  showPhoto(`/api/survey/batches/${batch.id}/photos/${photo.id}/preview.jpg`,`${photo.filename}. ${photo.placement.reason}`);
  showModel(photo.meta.byte_sha256);
  if(setDate && photo.meta.captured_local){$('capture-date').value=photo.meta.captured_local.slice(0,10);clearBatchRun();}
  document.querySelectorAll('.photo-tile').forEach(el=>el.setAttribute('aria-pressed',el.dataset.photoId===photo.id));
  renderMap();refreshState();
}
function renderBatch() {
  $('survey-summary').hidden=!batch;
  $('photo-count').textContent=batch?`${batch.photos.length} photo${batch.photos.length===1?'':'s'}`:source?'1 photo':'None yet';
  if(!batch){$('photo-list').replaceChildren();renderSurveyImage();refreshState();return;}
  const result=batch.result;
  const groups=result?result.placed-result.links.length:0;
  $('batch-progress').textContent=result?(result.placed?`${result.placed} of ${batch.photos.length} photos on the map${groups>1?`, ${groups} groups need alignment review`:''}${result.unplaced?`, ${result.unplaced} unplaced`:''}. Trace the farmland across the images.`:'These photos could not be placed automatically. Draw on the reference map or import a boundary; the photos can still be checked.'):batch.message;
  $('build-batch').hidden=!['draft','failed'].includes(batch.status)||!batch.photos.length;
  const list=$('photo-list');list.replaceChildren();
  for(const photo of batch.photos){
    const tile=node('button',null,'photo-tile');tile.dataset.photoId=photo.id;tile.setAttribute('aria-pressed',photo.id===batchPhoto);tile.setAttribute('aria-label',`${photo.filename}: ${photo.placement.corners?'Placed approximately':'Unplaced'}`);
    const img=node('img');img.src=`/api/survey/batches/${batch.id}/photos/${photo.id}/preview.jpg`;img.alt='';img.loading='lazy';
    tile.append(img,node('small',photo.filename),node('small',photo.placement.corners?'Placed approximately':'Unplaced',''+(photo.placement.corners?'':'unplaced')));tile.title=photo.placement.reason;tile.onclick=()=>chooseBatchPhoto(photo);list.append(tile);
  }
  renderSurveyImage();refreshState();updateCoverage();
  const chosen=batch.photos.find(p=>p.id===batchPhoto);
  if(chosen)$('photo-caption').textContent=`${chosen.filename}. ${chosen.placement.reason}`;
}
async function updateCoverage() {
  const version=++coverageVersion; $('coverage-note').hidden=true;reviewCoverage=null;renderReviewSummary();
  if(!selected || batch?.status!=='ready')return;
  const batchId=batch.id,parcelId=selected.id;
  try{const result=await api(`batches/${batchId}/coverage`,{parcel_id:parcelId});if(version!==coverageVersion)return;
    reviewCoverage={...result,batch_id:batchId,parcel_id:parcelId};renderReviewSummary();
    $('coverage-note').textContent=result.percent===null?result.message:`About ${result.percent}% of this boundary lies under the estimated photo footprints. Whole-property coverage remains unverified.`;
    $('coverage-note').hidden=false;
  }catch(e){if(version===coverageVersion){$('coverage-note').textContent=e.message;$('coverage-note').hidden=false;}}
}
async function refreshBatches() {
  const state=await api('bootstrap');bootstrap.batches=state.batches;
  bootstrap.worlds=state.worlds;renderWorldHistory();
  if(!currentWorld && state.worlds?.length){renderWorld(state.worlds[0]);if(['queued','processing'].includes(currentWorld.status))pollWorld(currentWorld.id);}
  $('saved-batches-label').hidden=!state.batches?.length;
  const select=$('saved-batches');select.replaceChildren(new Option('Choose a photo batch',''));
  for(const item of state.batches || [])select.add(new Option(`${new Date(item.created*1000).toLocaleString()} (${item.count} photos, ${item.status})`,item.id));
  if(batch)select.value=batch.id;
}
function pollBatch(ident, fitWhenReady = true) {
  clearTimeout(batchTimer);
  batchTimer=setTimeout(async()=>{
    if(batch?.id!==ident)return;
    try{const next=await api(`batches/${ident}`);if(batch?.id!==ident)return;batch=next;
      if(batch.status==='building'){$('batch-progress').textContent=batch.message;pollBatch(ident,fitWhenReady);}
      else{renderBatch();if(fitWhenReady && surveyPoints().length)fit(surveyPoints());if(!points.length)setMode('draw');await refreshBatches();message(batch.status==='ready'?`${batch.message} Draw or edit the farmland boundary, then save it.`:batch.message,batch.status==='failed');}
    }catch(e){message(`Unable to refresh survey: ${e.message}. Select it from Earlier photo batches to reconnect.`,true);}
  },900);
}
async function buildBatch() {
  batch=await api(`batches/${batch.id}/build`,{});renderBatch();
  if(batch.status==='building')pollBatch(batch.id);else if(surveyPoints().length)fit(surveyPoints());
}
async function loadBatch(ident) {
  clearTimeout(batchTimer);clearBatchRun();clearRetry();hideAssessment();batchPhoto=null;
  batch=await api(`batches/${ident}`);renderBatch();
  if(batch.photos.length)chooseBatchPhoto(batch.photos[0]);
  if(surveyPoints().length)fit(surveyPoints());
  if(batch.status==='building')pollBatch(ident);
}
async function encodeFile(file) {
  const bytes=new Uint8Array(await file.arrayBuffer());let binary='';
  for(let i=0;i<bytes.length;i+=32768)binary+=String.fromCharCode(...bytes.subarray(i,i+32768));
  return btoa(binary);
}
async function uploadBatch(files, demo = false) {
  const count=demo?bootstrap.map.demo_batch.length:files.length;
  if(!count)return;
  if(count>(bootstrap.map.max_batch_photos||24))throw Error('Use at most 24 photos per demo batch.');
  if(!demo && files.some(file=>file.size>20*1024*1024))throw Error('Each photo must be no larger than 20 MiB.');
  busy=true;hideAssessment();clearRetry();clearBatchRun();clearTimeout(batchTimer);refreshState();
  $('upload-errors').hidden=true;
  const failures=[];let duplicates=0;
  try{
    batch=await api('batches',{});batchPhoto=null;source=null;camera=null;$('photo').hidden=true;$('photo-empty').hidden=false;showModel(null);renderBatch();
    for(let index=0;index<count;index++){
      $('batch-progress').textContent=`Reading photo ${index+1} of ${count}…`;
      try{const request=demo?{source:'example_batch',index}:{source:'upload',filename:files[index].name,file_base64:await encodeFile(files[index])};
        const result=await api(`batches/${batch.id}/photos`,request);if(result.duplicate)duplicates++;
      }catch(e){failures.push(`${demo?bootstrap.map.demo_batch[index].filename:files[index].name}: ${e.message}`);}
    }
    batch=await api(`batches/${batch.id}`);renderBatch();await refreshBatches();
    if(batch.photos.length)await buildBatch();
    if(failures.length){$('upload-errors').textContent=`${failures.length} photo(s) were not added. ${failures.join(' ')}`;$('upload-errors').hidden=false;message('Some files could not be added. Their errors are listed with the photos.',true);}
    else if(duplicates)message(`${duplicates} repeated file(s) kept only once in this batch.`);
  }finally{
    busy=false;refreshState();
    if(batch?.photos.length)chooseBatchPhoto(batch.photos[0]);
    $('upload').value='';
  }
}
function clearBatchRun(){batchRun=null;$('retry-batch').hidden=true;$('batch-results').hidden=true;$('batch-results').replaceChildren();renderReviewSummary();}
function renderBatchResults(){
  $('batch-results').hidden=!batchRun?.reports.length;$('batch-results').replaceChildren();
  for(const report of batchRun?.reports || []){const button=node('button');const fails=report.checks.filter(c=>c.status==='FAIL').length;
    button.append(node('span',report.filename),node('span',fails?`${fails} conflicts`:'No conflicts','status '+(fails?'FAIL':'PASS')));
    button.onclick=()=>showReport(report);$('batch-results').append(button);}
  renderReviewSummary();
}
async function checkBatch(resume = false) {
  if(!resume)batchRun={batch_id:batch.id,parcel_id:selected.id,date:$('capture-date').value,photos:batch.photos.map(p=>p.id),reports:[],request:null};
  const run=batchRun;if(!run)return;
  busy=true;hideAssessment();clearRetry();refreshState();$('retry-batch').hidden=true;
  try{
    while(run.reports.length<run.photos.length){
      const index=run.reports.length;$('check-batch').textContent=`Checking photo ${index+1} of ${run.photos.length}…`;
      if(!run.request){const challenge=await api('challenges',{parcel_id:run.parcel_id,capture_date:run.date});
        run.request={source:'batch',batch_id:run.batch_id,photo_id:run.photos[index],parcel_id:run.parcel_id,capture_date:run.date,token:challenge.token,idempotency:crypto.randomUUID()};}
      const result=await api('submissions',run.request);run.reports.push(result.report);run.request=null;renderBatchResults();
    }
    await refreshHistory();showReport(run.reports[0],false);message(`Saved ${run.reports.length} photo assessments against the same boundary. Select a result to review it.`);
  }catch(e){$('retry-batch').hidden=false;throw e;}
  finally{busy=false;$('check-batch').textContent='Check all photos';refreshState();}
}

action('start-map',()=>{setMode('draw');$('map').scrollIntoView({behavior:'smooth',block:'center'});$('map').focus({preventScroll:true});});
action('start-upload',()=>$('upload').click());
action('example-batch',()=>uploadBatch([],true));
action('build-batch',buildBatch);
action('fit-survey',()=>fit(surveyPoints().length?surveyPoints():null));
action('check-batch',()=>checkBatch());action('retry-batch',()=>checkBatch(true));
for(const id of ['show-imagery','show-footprints'])$(id).addEventListener('change',renderSurveyImage);
$('saved-batches').addEventListener('change',async e=>{if(!e.target.value)return;try{await loadBatch(e.target.value);}catch(error){message(error.message,true);}});
action('draw',()=>setMode('draw')); action('edit',()=>setMode('edit'));
action('clear',()=>{if(!points.length)return;rememberPoints();points=[];dirty();setMode('draw');renderMap();renderVertices();});
action('undo',undoBoundary);
action('add-vertices',()=>{
  if(points.length<3 || points.length>=128)return;
  const edges=points.map((p,i)=>({index:i,length:Math.hypot(p[0]-points[(i+1)%points.length][0],p[1]-points[(i+1)%points.length][1])}));
  const split=new Set(edges.sort((a,b)=>b.length-a.length).slice(0,128-points.length).map(edge=>edge.index));
  const next=points.flatMap((p,i)=>split.has(i)?[[...p],midpoint(i)]:[[...p]]);
  rememberPoints();points=next;dirty();setMode('edit');renderVertices();
  message(`${points.length} vertices now. Drag the new white points to follow bends in the field edge. Undo restores the previous outline.`);
});
action('fit',fit);action('zoom-in',()=>zoom(.75));action('zoom-out',()=>zoom(1.3333));
action('example-boundary',()=>{rememberPoints();points=[[224,351],[286,327],[343,369],[690,508],[621,593],[463,526],[227,608],[214,520]];$('parcel-name').value='Jalogny pasture · example';dirty();setMode('edit');fit();renderVertices();message('Pasture outline loaded from visible field edges. It is an illustrative boundary, not a cadastral survey. Save it to use it.');});
action('save',async()=>{const parcel=await api('parcels',{name:$('parcel-name').value,map_vertices:points.map(toWorld)});bootstrap.parcels.unshift(parcel);useParcel(parcel);message(`Boundary saved: ${parcel.area_ha.toFixed(2)} hectares. Each assessment retains its own boundary snapshot.`);});
action('export-geojson',()=>download(`/api/survey/parcels/${selected.id}/export.geojson`));
action('example-photo',()=>{hideAssessment();clearTimeout(batchTimer);batch=null;batchPhoto=null;clearBatchRun();if(previewURL)URL.revokeObjectURL(previewURL);previewURL=null;source='example';encoded=null;filename=bootstrap.map.sample.filename;$('capture-date').value=bootstrap.map.sample.date;$('upload').value='';showPhoto('/example-preview.jpg',`Historical ICAERUS photo from ${bootstrap.map.sample.date}. Original bytes retain EXIF; this preview is stripped.`);showModel(bootstrap.map.sample.image_sha256);clearRetry();renderBatch();updateCoverage();});
action('submit',async()=>{busy=true;refreshState();try{const bound=selected.id,date=$('capture-date').value;const file=source==='batch'?{source,batch_id:batch.id,photo_id:batchPhoto}:{source,filename,file_base64:encoded};const challenge=await api('challenges',{parcel_id:bound,capture_date:date});lastRequest={...file,parcel_id:bound,capture_date:date,token:challenge.token,idempotency:crypto.randomUUID()};await sendSubmission(lastRequest);}finally{busy=false;refreshState();}});
action('retry',async()=>{if(!lastRequest)return;busy=true;refreshState();try{await sendSubmission(lastRequest);}finally{busy=false;refreshState();}});
action('export-report',()=>download(`/api/survey/reports/${activeReport.id}/export.json`));
action('verify-current',async()=>{const result=await api('verify',{report:activeReport});message(`${result.status}: ${result.message}`,result.status!=='PASS');});
$('saved-parcels').addEventListener('change',e=>{const p=bootstrap.parcels.find(p=>p.id===e.target.value);if(p)useParcel(p);});
$('parcel-name').addEventListener('input',dirty);$('capture-date').addEventListener('input',()=>{hideAssessment();clearRetry();clearBatchRun();refreshState();});
$('import-geojson').addEventListener('change',async e=>{try{const file=e.target.files[0];if(!file)return;if(file.size>200000)throw Error('Boundary file exceeds 200 KB.');const value=JSON.parse(await file.text());const name=typeof value.properties?.name==='string'?value.properties.name:$('parcel-name').value;const parcel=await api('parcels',{name,geometry:value});bootstrap.parcels.unshift(parcel);useParcel(parcel);message('GeoJSON boundary validated and saved.');}catch(e){message(e.message,true);}finally{$('import-geojson').value='';}});
$('verify-file').addEventListener('change',async e=>{try{const file=e.target.files[0];if(!file)return;if(file.size>2e6)throw Error('Assessment file exceeds 2 MB.');const result=await api('verify',{report:JSON.parse(await file.text())});message(`${result.status}: ${result.message}`,result.status!=='PASS');}catch(e){message(e.message,true);}finally{$('verify-file').value='';}});
$('upload').addEventListener('change',async e=>{try{await uploadBatch([...e.target.files]);}catch(error){message(error.message,true);}});
$('photo').addEventListener('error',()=>{message('This photo preview could not be displayed. Select a valid JPEG or PNG.',true);});
$('map').addEventListener('pointerdown',e=>{
  if(!bootstrap||busy||e.button!==0)return;
  const index=e.target.getAttribute('data-index'), edge=e.target.closest('[data-insert-after]');
  let vertex=mode==='edit'&&index!==null?Number(index):null,recorded=false;
  if(mode==='edit'&&edge){vertex=insertVertex(Number(edge.getAttribute('data-insert-after')));recorded=vertex!==null;renderMap();}
  drag={index:vertex,last:[e.clientX,e.clientY],view:[...view],unit:mapUnitsPerPixel(),moved:false,recorded};
  $('map').setPointerCapture(e.pointerId);
});
$('map').addEventListener('pointermove',e=>{
  if(!drag)return;const now=eventPoint(e);
  if(Math.hypot(e.clientX-drag.last[0],e.clientY-drag.last[1])>3)drag.moved=true;
  if(mode==='edit'&&drag.moved){if(drag.index!==null){if(!drag.recorded){rememberPoints();drag.recorded=true;}points[drag.index]=now;dirty();}
    else{view=[drag.view[0]-(e.clientX-drag.last[0])*drag.unit,drag.view[1]-(e.clientY-drag.last[1])*drag.unit,drag.view[2],drag.view[3]];}renderMap();}
});
$('map').addEventListener('pointerup',e=>{if(!drag)return;if(mode==='draw'&&!drag.moved){if(points.length>=128){message('Use at most 128 vertices.',true);}else{rememberPoints();points.push(eventPoint(e));dirty();}}drag=null;renderMap();renderVertices();});
$('map').addEventListener('pointercancel',()=>{drag=null;renderVertices();});
$('map').addEventListener('wheel',e=>{e.preventDefault();zoom(e.deltaY>0?1.15:1/1.15,eventPoint(e));},{passive:false});
$('map').addEventListener('keydown',e=>{
  if(busy)return;
  const edge=e.target.closest('[data-insert-after]');
  if(edge&&(e.key==='Enter'||e.key===' ')){e.preventDefault();insertVertex(Number(edge.getAttribute('data-insert-after')));renderMap();renderVertices();$('map').focus();return;}
  if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='z'){e.preventDefault();undoBoundary();return;}
  if(e.key==='Escape')setMode('edit');
  if((e.key==='Backspace'||e.key==='Delete')&&points.length){e.preventDefault();rememberPoints();points.pop();dirty();renderMap();renderVertices();}
  if(e.key==='+'||e.key==='=')zoom(.75);if(e.key==='-')zoom(1.3333);
});
new ResizeObserver(()=>{if(!bootstrap)return;const rect=$('map').getBoundingClientRect();const width=view[3]*rect.width/rect.height;view=[view[0]+(view[2]-width)/2,view[1],width,view[3]];renderMap();}).observe($('map'));
(async()=>{try{bootstrap=await api('bootstrap');csrf=bootstrap.csrf_token;$('capture-date').value=new Date().toISOString().slice(0,10);savedOptions();renderHistory();fit();refreshState();await refreshBatches();const reviewId=new URL(location.href).searchParams.get('review');const job=bootstrap.worlds?.find(item=>item.id===reviewId);if(job?.status==='ready')await reviewWorldSurvey(job,false);}catch(e){message(e.message,true);}})();

function refreshWorldButton() {
  const building=worldSubmitting;
  $('build-world').disabled=busy || building || batch?.status!=='ready' || points.length<3;
  $('build-world').textContent=building?'Starting build…':'Build world ↗';
  $('world-hint').textContent=batch?.status==='building'?'Preparing your photo map…':
    !batch?.photos.length?'Upload photos, then draw the field boundary.':
    points.length<3?'Draw at least three corners around your field.':
    !selected?'Your boundary will be saved when you build.':'Ready. The world will use this saved boundary and photo batch.';
}
function renderWorldHistory() {
  const jobs=bootstrap?.worlds || [];const list=$('world-history');list.replaceChildren();
  $('world-history-details').hidden=!jobs.length;
  for(const job of jobs){const b=node('button',`${job.result?.name || 'Field world'} · ${job.status} · ${new Date(job.created_utc).toLocaleString()}`);
    b.onclick=()=>{renderWorld(job);if(['queued','processing'].includes(job.status))pollWorld(job.id);};list.append(b);}
}
function rememberWorldReview(job) {
  const url=new URL(location.href);url.searchParams.set('review',job.id);
  history.replaceState(null,'',url);
}
async function reviewWorldSurvey(job,scroll=true) {
  const parcel=bootstrap.parcels.find(item=>item.id===job.parcel_id);
  if(!parcel)throw Error('This saved boundary is not in the recent list. Import its saved boundary to review the survey.');
  await loadBatch(job.batch_id);useParcel(parcel);renderWorld(job);rememberWorldReview(job);
  if(scroll)$('review-summary').scrollIntoView({behavior:'smooth',block:'start'});
}
function renderWorld(job) {
  currentWorld=job;$('world-current').hidden=false;$('world-current').dataset.status=job.status;
  $('world-status').textContent={queued:'World queued',processing:'Building your field',ready:'Your world is ready',failed:'Build needs attention'}[job.status];
  $('world-progress').textContent=job.message.includes('No space left on device')?'There is not enough disk space to finish this world. Free some space, then retry; the uploaded photos and saved inputs are retained.':job.message;$('retry-world').hidden=job.status!=='failed';
  const result=$('world-result');result.replaceChildren();
  if(job.result && job.status==='ready'){
    const r=job.result;
    result.append(node('p',`${r.cows} cow observations from ${r.photos} photos · ${r.coverage_percent}% estimated image coverage · last build attempt ${Math.round(r.seconds)} s`));
    result.append(node('p',`Automatic draft: ${r.unknown_heads} head directions unknown, ${r.appearance_flagged} displayed coats or matches flagged. Retained for review: ${r.boundary_review} edge sightings, ${r.appearance_review || 0} failed coats, ${r.placement_review || 0} crowded placements. ${r.outside_boundary} sightings outside the boundary; ${r.merged_sightings} overlapping sightings merged.`,'hint'));
    const links=node('div',null,'world-links');const open=node('a','Enter world ↗','primary');open.href=job.url;
    links.append(open);
    open.onclick=()=>rememberWorldReview(job);
    const review=node('button','Review this survey');review.onclick=async()=>{
      try{await reviewWorldSurvey(job);}catch(error){message(error.message,true);}
    };links.append(review);
    const bundleLink=node('a','Download replay bundle');bundleLink.href=`/api/survey/worlds/${job.id}/replay.zip`;links.append(bundleLink);
    for(const [label,path] of [[r.appearance_review===undefined?'All observations':'Review findings',r.appearance_review===undefined?'observations.json':'survey-observations.html'],['Build details','build-manifest.json'],['Saved boundary','boundary.geojson']]){
      const a=node('a',label);a.href=job.url+path;a.target='_blank';a.rel='noopener';links.append(a);
    }
    result.append(links);
  }
  refreshWorldButton();
  renderReviewSummary();
}

function renderReviewSummary() {
  const worlds = [currentWorld, ...(bootstrap?.worlds || [])];
  const matchingWorld = worlds.find(job => job?.status === 'ready' && job.batch_id === batch?.id && job.parcel_id === selected?.id);
  const summary = buildHerdProofReviewSummary({parcel:selected,report:activeReport,model:bootstrap?.map.model,
    batch,world:matchingWorld,coverage:reviewCoverage,batchRun});
  $('review-scope').textContent=summary.scope;
  $('review-state').textContent=summary.state;
  $('review-next-action').textContent=summary.nextAction;
  $('review-metrics').replaceChildren(...summary.cards.map(card => {
    const item=node('div');item.append(node('dt',card.label),node('dd',card.value));
    const detail=node('dd');detail.append(node('p',card.detail));item.append(detail);return item;
  }));
  const links=$('review-links');links.replaceChildren();
  if(summary.reportId){const link=node('a','Export selected assessment');link.href=`/api/survey/reports/${summary.reportId}/export.json`;link.download='';links.append(link);}
  if(summary.worldUrl){const link=node('a','Review world observations ↗');link.href=summary.worldUrl+(matchingWorld.result.appearance_review===undefined?'observations.json':'survey-observations.html');links.append(link);}
}
function pollWorld(id) {
  clearTimeout(worldTimer);worldTimer=setTimeout(async()=>{
    if(currentWorld?.id!==id)return;
    try {const job=await api(`worlds/${id}`);if(currentWorld?.id!==id)return;renderWorld(job);
      if(['queued','processing'].includes(job.status))pollWorld(id);else await refreshBatches();
    } catch(e) {$('world-progress').textContent='Connection interrupted. Reconnecting to the saved build…';pollWorld(id);}
  },1800);
}
action('build-world',async()=>{
  worldSubmitting=true;refreshWorldButton();
  try {
    if(!selected){const p=await api('parcels',{name:$('parcel-name').value,map_vertices:points.map(toWorld)});bootstrap.parcels.unshift(p);useParcel(p);}
    const job=await api('worlds',{batch_id:batch.id,parcel_id:selected.id});renderWorld(job);
    if(['queued','processing'].includes(job.status))pollWorld(job.id);
    await refreshBatches();
  } finally {worldSubmitting=false;refreshWorldButton();}
});
action('retry-world',async()=>{const job=await api(`worlds/${currentWorld.id}/retry`,{});renderWorld(job);pollWorld(job.id);});
