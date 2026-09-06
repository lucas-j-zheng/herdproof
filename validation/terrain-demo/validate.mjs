import assert from 'node:assert/strict';
import {readFile,writeFile} from 'node:fs/promises';
import {resolve,dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
import RAPIER from '@dimforge/rapier3d-compat/rapier.es.js';
import {makeTerrain} from './terrain.js';
const base=resolve(process.argv[2]||resolve(dirname(fileURLToPath(import.meta.url)),'public'));
const config=JSON.parse(await readFile(resolve(base,'scene.json'),'utf8'));
const buffer=await readFile(resolve(base,'heights.bin'));const heights=new Float32Array(buffer.buffer.slice(buffer.byteOffset,buffer.byteOffset+buffer.byteLength));
const terrain=makeTerrain(config.terrain,heights);
// Non-planar cell distinguishes triangle interpolation from bilinear smoothing.
const toy=makeTerrain({width:2,height:2,spacing:2,minX:10,minZ:20},new Float32Array([0,2,4,10]));
assert.equal(toy.sample(10.5,20.5).height,1.5);assert.equal(toy.sample(11.5,21.5).height,6.5);
assert.equal(toy.sample(12,22).height,10);assert.equal(toy.sample(9.99,20).valid,false);assert.equal(toy.sample(NaN,20).valid,false);
assert.deepEqual([...toy.indices],[0,2,1,1,2,3]);
await RAPIER.init();const world=new RAPIER.World({x:0,y:-9.81,z:0});
world.createCollider(RAPIER.ColliderDesc.trimesh(terrain.positions,terrain.indices));world.step();
let seed=41,maxError=0;const random=()=>{seed=(Math.imul(seed,1664525)+1013904223)|0;return(seed>>>0)/4294967296;};
const s=config.terrain,spanX=(s.width-1)*s.spacing,spanZ=(s.height-1)*s.spacing;
const top=Math.max(...heights.subarray(0,1))+Math.max(100,s.maxAltitude-config.origin.altitude+20);
for(let i=0;i<1000;i++){const x=s.minX+random()*spanX,z=s.minZ+random()*spanZ;const hit=world.castRay(new RAPIER.Ray({x,y:top,z},{x:0,y:-1,z:0}),top+1000,true);assert(hit,'Missing collision triangle');maxError=Math.max(maxError,Math.abs(top-hit.timeOfImpact-terrain.sample(x,z).height));}
assert(maxError<.01,`Renderer/collider mismatch ${maxError}`);
const report={passed:true,nonplanar_triangle_test:true,invalid_area_rejected:true,collider_samples:1000,render_collider_max_error_m:maxError,vertices:terrain.positions.length/3,triangles:terrain.indices.length/3};
await writeFile(resolve(base,'collision-validation.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report,null,2));world.free();
