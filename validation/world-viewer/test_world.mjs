import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import * as THREE from 'three';
import RAPIER from '@dimforge/rapier3d-compat/rapier.es.js';
import {makeTerrain} from './terrain.js';
import {coatMaterial} from './coat.js';

const toy=makeTerrain({width:2,height:2,spacing:2,minX:10,minZ:20},new Float32Array([0,2,4,10]));
assert.equal(toy.sample(10.5,20.5).height,1.5);assert.equal(toy.sample(11.5,21.5).height,6.5);
assert.equal(toy.sample(9,20).valid,false);assert.equal(toy.sample(NaN,20).valid,false);
const hole=makeTerrain(toy.spec,toy.heights,new Uint8Array([1,1,1,0]));
assert.equal(hole.indices.length,3);assert.equal(hole.sample(11.5,21.5).valid,false);assert.equal(hole.sample(10.5,20.5).valid,true);
const base=new THREE.MeshStandardMaterial(),a=coatMaterial(base,'#ff0000'),b=coatMaterial(base,'#ffffff');
assert.notEqual(a,b);assert.notEqual(a.userData.coatColor,b.userData.coatColor);
a.userData.coatColor.set('#000000');assert.equal(b.userData.coatColor.getHexString(),'ffffff');assert.equal(base.color.getHexString(),'ffffff');
const shader=()=>({uniforms:{},vertexShader:'#include <common>\n#include <begin_vertex>',fragmentShader:'#include <common>\n#include <map_fragment>'});
const sa=shader(),sb=shader();a.onBeforeCompile(sa);b.onBeforeCompile(sb);assert.notEqual(sa.uniforms.cowCoatColor.value,sb.uniforms.cowCoatColor.value);
await RAPIER.init();
const results=[];
for(const dir of process.argv.slice(2)){
 const path=resolve(dir),scene=JSON.parse(await readFile(resolve(path,'scene.json'),'utf8'));
 const raw=await readFile(resolve(path,'heights.bin')),valid=await readFile(resolve(path,'valid.bin'));
 const terrain=makeTerrain(scene.terrain,new Float32Array(raw.buffer.slice(raw.byteOffset,raw.byteOffset+raw.byteLength)),new Uint8Array(valid));
 const world=new RAPIER.World({x:0,y:-9.81,z:0});world.createCollider(RAPIER.ColliderDesc.trimesh(terrain.positions,terrain.indices));world.step();
 let seed=9123,maxError=0,samples=0;const random=()=>{seed=(Math.imul(seed,1664525)+1013904223)|0;return(seed>>>0)/4294967296;};
 const s=scene.terrain,top=s.maxAltitude-scene.origin.altitude+20;
 for(let i=0;i<1000;i++){const x=s.minX+random()*(s.width-1)*s.spacing,z=s.minZ+random()*(s.height-1)*s.spacing,p=terrain.sample(x,z);if(!p.valid)continue;
  const hit=world.castRay(new RAPIER.Ray({x,y:top,z},{x:0,y:-1,z:0}),1000,true);assert(hit);maxError=Math.max(maxError,Math.abs(top-hit.timeOfImpact-p.height));samples++;}
 assert(maxError<.01);assert(samples>0);results.push({scene:scene.scene_id,samples,maxColliderError_m:maxError,passed:true});world.free();
}
console.log(JSON.stringify({passed:true,nonplanarTriangles:true,missingCells:true,independentCoatMaterials:true,scenes:results},null,2));
