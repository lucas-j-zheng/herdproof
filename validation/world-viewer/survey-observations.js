'use strict';
const filter=document.getElementById('filter'),list=document.getElementById('observations');let scene;
const labels={proposed:'Displayed · unreviewed',merged:'Possible duplicate · merged',outside_boundary:'Outside boundary',boundary_review:'Near boundary · needs review',appearance_review:'Coat estimation failed',placement_review:'Crowded placement · needs review'};
function el(tag,text){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;}
function render(){list.replaceChildren();const shown=new Set(scene.cows.map(c=>c.id));
 for(const row of scene.detectionReview){const attention=row.status.endsWith('_review') || row.quality_flags.length>0;
  if(filter.value==='attention'&&!attention || filter.value==='displayed'&&!shown.has(row.id))continue;
  const card=el('article'),img=el('img');img.src=row.source_crop;img.alt='Original drone crop for '+row.id;img.loading='lazy';
  const status=el('p',labels[row.status]||row.status);status.className='status'+(shown.has(row.id)?' displayed':'');
  card.append(img,el('h2',row.id),status);
  if(row.exclusion_reason)card.append(el('p',row.exclusion_reason));
  if(row.merge_into)card.append(el('p','Shown with '+row.merge_into));
  if(row.conflicts_with)card.append(el('p','Overlaps '+row.conflicts_with));
  if(shown.has(row.id))card.append(el('p',`Apparent coat ${row.coat_color}. Head direction unknown.`));
  if(row.quality_flags.length)card.append(el('p','Flags: '+row.quality_flags.map(x=>x.replaceAll('_',' ')).join('; ')));
  const source=el('a','Open original photograph ↗');source.href=row.source_image;source.target='_blank';source.rel='noopener';card.append(source);list.append(card);
 }if(!list.children.length)list.append(el('p','No observations in this group.'));
}
filter.onchange=render;
fetch('scene.json').then(r=>{if(!r.ok)throw Error('Could not load observations');return r.json();}).then(data=>{scene=data;document.getElementById('summary').textContent=`${scene.cows.length} displayed cows; ${scene.detectionReview.length} retained sightings from ${scene.photos.length} original photos.`;render();}).catch(e=>document.getElementById('summary').textContent=e.message);
