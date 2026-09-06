import * as THREE from 'three';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import {Sky} from 'three/addons/objects/Sky.js';
import RAPIER from 'rapier';
import {makeTerrain} from './terrain.js';
import {coatMaterial} from './coat.js';
import {post,savePatch} from './api.js';

window.addEventListener('unhandledrejection',e=>{const el=document.querySelector('#load-status');if(el)el.textContent=e.reason?.message||String(e.reason);});
const $=s=>document.querySelector(s),V=THREE.Vector3;
const delay=ms=>new Promise(r=>setTimeout(r,ms));
let toastTimer;function toast(s){$('#toast').textContent=s;$('#toast').classList.add('show');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').classList.remove('show'),4200);}
const renderer=new THREE.WebGLRenderer({antialias:true,alpha:false,preserveDrawingBuffer:true,powerPreference:'high-performance'});
renderer.setPixelRatio(1);renderer.setSize(innerWidth,innerHeight);renderer.setClearColor(0xd1dcd2);
renderer.outputColorSpace=THREE.SRGBColorSpace;renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.05;
renderer.shadowMap.enabled=true;renderer.shadowMap.type=THREE.PCFSoftShadowMap;
$('#view').append(renderer.domElement);
const scene=new THREE.Scene();scene.fog=new THREE.FogExp2(0xc6d7c5,.0020);
const camera=new THREE.PerspectiveCamera(52,innerWidth/innerHeight,.08,1600);
camera.position.set(110,125,135);
const controls=new OrbitControls(camera,renderer.domElement);controls.target.set(0,1,-10);controls.enableDamping=true;controls.maxPolarAngle=Math.PI*.48;controls.minDistance=5;controls.maxDistance=280;
const sky=new Sky();sky.scale.setScalar(4000);scene.add(sky);
Object.assign(sky.material.uniforms.turbidity,{value:3});sky.material.uniforms.rayleigh.value=2.6;sky.material.uniforms.mieCoefficient.value=.003;sky.material.uniforms.mieDirectionalG.value=.82;
const sun=new V(-.45,.72,.42).normalize();sky.material.uniforms.sunPosition.value.copy(sun);
scene.add(new THREE.HemisphereLight(0xe4f1ff,0x62704b,1.4));
const sunlight=new THREE.DirectionalLight(0xfff0da,2.6);sunlight.position.copy(sun).multiplyScalar(100);sunlight.castShadow=true;
sunlight.shadow.mapSize.set(2048,2048);Object.assign(sunlight.shadow.camera,{left:-65,right:65,top:65,bottom:-65,near:1,far:260});sunlight.shadow.normalBias=.025;sunlight.shadow.bias=-.00015;scene.add(sunlight,sunlight.target);
const textureLoader=new THREE.TextureLoader();
const config=await fetch('scene.json').then(r=>r.json());
const surveyWorld=config.workflow?.type==='uploaded_survey';
if(surveyWorld){
 document.body.classList.add('survey-world');
 $('#intro p').textContent='Your uploaded photos and field boundary, rebuilt on measured ground elevations.';
 $('footer span').textContent='Uploaded survey photos · Elevation: IGN · Automatic draft';
 for(const id of ['flip-cow','coat-swatch','save-coat','review-link','checks'])$('#'+id).hidden=true;
 for(const a of document.querySelectorAll('a[href="review.html"]')){a.href='/';a.textContent='Back to field builder ↗';}
 const findings=document.createElement('a');findings.href='survey-observations.html';findings.textContent='Review findings ↗';$('#toolbar').append(findings);
 const info=$('#info').querySelectorAll('p');info[1].textContent='Photo placement uses camera metadata and matched background features. It remains approximate when draped over measured terrain.';
 info[2].textContent='Cows are automatic, unreviewed detections. Coats and body axes are estimated from their original photographs; head direction remains unknown.';
 const evidence=$('#info a[href="camera.json"]');evidence.href='observations.json';evidence.textContent='Observation and photo evidence ↗';
}
const spec=config.terrain,MIN_X=spec.minX,MIN_Z=spec.minZ,SPAN_X=(spec.width-1)*spec.spacing,SPAN_Z=(spec.height-1)*spec.spacing,MAX_X=MIN_X+SPAN_X,MAX_Z=MIN_Z+SPAN_Z,CENTRE_X=(MIN_X+MAX_X)/2,CENTRE_Z=(MIN_Z+MAX_Z)/2;
const overviewScale=Math.max(SPAN_X,SPAN_Z);camera.position.set(CENTRE_X+overviewScale*.55,overviewScale*.625,CENTRE_Z+overviewScale*.675);controls.target.set(CENTRE_X,1,CENTRE_Z-10);
document.title='HerdProof · '+config.name+' field';$('#intro h1').textContent='Walk the field.';$('.field-title').textContent=config.name+' · '+config.date;$('.map-caption span').textContent=SPAN_X+' m × '+SPAN_Z+' m';

const [buffer,validBuffer,groundMap,gltf,cowNormal]=await Promise.all([
 fetch('heights.bin').then(r=>r.arrayBuffer()),fetch('valid.bin').then(r=>r.arrayBuffer()),textureLoader.loadAsync('ground.jpg'),new GLTFLoader().loadAsync('assets/cow-original.glb'),textureLoader.loadAsync('assets/cow-normal.png'),RAPIER.init()
]);
const terrain=makeTerrain(config.terrain,new Float32Array(buffer),new Uint8Array(validBuffer));
groundMap.colorSpace=THREE.SRGBColorSpace;groundMap.anisotropy=renderer.capabilities.getMaxAnisotropy();
const world=new RAPIER.World({x:0,y:-9.81,z:0});world.timestep=1/60;
function terrainMesh(data,map){const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.BufferAttribute(data.positions,3));g.setAttribute('uv',new THREE.BufferAttribute(data.uvs,2));g.setIndex(new THREE.BufferAttribute(data.indices,1));g.computeVertexNormals();const m=new THREE.MeshStandardMaterial({map,roughness:1,color:0xdce2c7});const mesh=new THREE.Mesh(g,m);mesh.receiveShadow=true;scene.add(mesh);return mesh;}
const groundMesh=terrainMesh(terrain,groundMap);
const grainSize=256,grain=new Uint8Array(grainSize*grainSize*4);let grainSeed=config.procedural_seeds.ground_grain;
for(let i=0;i<grain.length;i+=4){grainSeed=(Math.imul(grainSeed,1664525)+1013904223)|0;const v=95+(grainSeed>>>24)*.27;grain[i]=grain[i+1]=grain[i+2]=v;grain[i+3]=255;}
const grainTexture=new THREE.DataTexture(grain,grainSize,grainSize);grainTexture.wrapS=grainTexture.wrapT=THREE.RepeatWrapping;grainTexture.repeat.set(110,110);grainTexture.magFilter=THREE.LinearFilter;grainTexture.minFilter=THREE.LinearMipmapLinearFilter;grainTexture.generateMipmaps=true;grainTexture.needsUpdate=true;groundMesh.material.bumpMap=grainTexture;groundMesh.material.bumpScale=.019;
const groundCollider=world.createCollider(RAPIER.ColliderDesc.trimesh(terrain.positions,terrain.indices));
const boundaryBody=world.createRigidBody(RAPIER.RigidBodyDesc.fixed());
for(const [x,z,hx,hz] of [[MIN_X+1,CENTRE_Z,.25,SPAN_Z/2],[MAX_X-1,CENTRE_Z,.25,SPAN_Z/2],[CENTRE_X,MIN_Z+1,SPAN_X/2,.25],[CENTRE_X,MAX_Z-1,SPAN_X/2,.25]])world.createCollider(RAPIER.ColliderDesc.cuboid(hx,50,hz).setTranslation(x,20,z),boundaryBody);
const player=world.createRigidBody(RAPIER.RigidBodyDesc.kinematicPositionBased().setTranslation(0,4,0));
const playerCollider=world.createCollider(RAPIER.ColliderDesc.capsule(.55,.3),player);
const controller=world.createCharacterController(.015);controller.setMaxSlopeClimbAngle(Math.PI*.23);controller.setMinSlopeSlideAngle(Math.PI*.27);controller.enableSnapToGround(.35);controller.enableAutostep(.22,.25,false);
let mode='overview',selected=null,autoTarget=null,velocityY=0,yaw=0,pitch=0,drag=false,lastPointer=null;
const keys=new Set(),cows=[],obstacles=[],hoofChecks=[];
let randomSeed=config.procedural_seeds.features;function random(){randomSeed=(Math.imul(randomSeed,1664525)+1013904223)|0;return(randomSeed>>>0)/4294967296;}
const dummy=new THREE.Object3D(),color=new THREE.Color();
function geometryAt(g,m,position,scale){const mesh=new THREE.Mesh(g,m);mesh.position.fromArray(position);if(scale)mesh.scale.fromArray(scale);mesh.castShadow=true;mesh.receiveShadow=true;scene.add(mesh);return mesh;}
const wood=new THREE.MeshStandardMaterial({color:0x827561,roughness:1});
const fencePosts=[],fenceSegments=[];
for(const path of config.fences){for(let i=0;i<path.length-1;i++){const a=new V().fromArray(path[i]),b=new V().fromArray(path[i+1]);const n=Math.ceil(a.distanceTo(b)/3.7);for(let j=0;j<n;j++){const p=a.clone().lerp(b,j/n);const s=terrain.sample(p.x,p.z);if(!s.valid)continue;p.y=s.height;fencePosts.push(p);}fenceSegments.push([a,b]);}}
const posts=new THREE.InstancedMesh(new THREE.CylinderGeometry(.055,.07,1.15,6),wood,fencePosts.length);posts.castShadow=true;posts.receiveShadow=true;
fencePosts.forEach((p,i)=>{dummy.position.copy(p).add(new V(0,.55,0));dummy.rotation.set(0,i*.31,Math.sin(i)*.04);dummy.scale.set(1,1,1);dummy.updateMatrix();posts.setMatrixAt(i,dummy.matrix);});scene.add(posts);
const wires=[];for(const [a,b] of fenceSegments){const steps=Math.ceil(a.distanceTo(b)/1.5);for(const h of [.45,.82,1.1])for(let j=0;j<steps;j++){const p=a.clone().lerp(b,j/steps),q=a.clone().lerp(b,(j+1)/steps);p.y=terrain.sample(p.x,p.z).height+h;q.y=terrain.sample(q.x,q.z).height+h;wires.push(...p.toArray(),...q.toArray());}
 const mid=a.clone().add(b).multiplyScalar(.5),length=Math.hypot(b.x-a.x,b.z-a.z),angle=Math.atan2(b.x-a.x,b.z-a.z);
 const desc=RAPIER.ColliderDesc.cuboid(.045,1,length/2).setTranslation(mid.x,terrain.sample(mid.x,mid.z).height+.5,mid.z).setRotation({x:0,y:Math.sin(angle/2),z:0,w:Math.cos(angle/2)});obstacles.push(world.createCollider(desc));}
const wireGeo=new THREE.BufferGeometry();wireGeo.setAttribute('position',new THREE.Float32BufferAttribute(wires,3));scene.add(new THREE.LineSegments(wireGeo,new THREE.LineBasicMaterial({color:0x8e9690,transparent:true,opacity:.58})));

// One aerial-reviewed tree; branch and leaf detail is illustrative.
const treeLeaves=new THREE.Group();scene.add(treeLeaves);
for(const t of config.trees){const p=new V().fromArray(t.position);geometryAt(new THREE.CylinderGeometry(.25,.55,6,11),new THREE.MeshStandardMaterial({color:0x675c43,roughness:1}),[p.x,p.y+3,p.z]);obstacles.push(world.createCollider(RAPIER.ColliderDesc.cylinder(3,.65).setTranslation(p.x,p.y+3,p.z)));
 const leafCanvas=document.createElement('canvas');leafCanvas.width=128;leafCanvas.height=128;const lc=leafCanvas.getContext('2d');
 for(let n=0;n<9;n++){const x=28+(n%3)*30,y=23+Math.floor(n/3)*36;lc.save();lc.translate(x,y);lc.rotate((n%2?1:-1)*.55);const gradient=lc.createLinearGradient(-12,0,12,0);gradient.addColorStop(0,'#809751');gradient.addColorStop(.5,'#a5ad65');gradient.addColorStop(1,'#516e33');lc.fillStyle=gradient;lc.beginPath();lc.moveTo(0,-20);lc.bezierCurveTo(19,-7,17,12,0,21);lc.bezierCurveTo(-15,10,-18,-6,0,-20);lc.fill();lc.strokeStyle='#52683b';lc.lineWidth=.8;lc.beginPath();lc.moveTo(0,-16);lc.lineTo(0,18);lc.stroke();lc.restore();}
 const leafTex=new THREE.CanvasTexture(leafCanvas);leafTex.colorSpace=THREE.SRGBColorSpace;
 const leafGeo=new THREE.PlaneGeometry(.65,.65);const leafMat=new THREE.MeshStandardMaterial({map:leafTex,alphaTest:.5,side:THREE.DoubleSide,roughness:1});const clumps=new THREE.InstancedMesh(leafGeo,leafMat,18000);
 for(let i=0;i<18000;i++){const angle=random()*Math.PI*2,r=Math.sqrt(random())*t.radius;const canopy=Math.sqrt(Math.max(0,1-r*r/t.radius**2));dummy.position.set(p.x+Math.cos(angle)*r,p.y+6.5+canopy*3.3+(random()-.4)*3,p.z+Math.sin(angle)*r);dummy.rotation.set(random()*Math.PI,random()*Math.PI*2,random()*Math.PI);dummy.scale.setScalar(.8+random()*.75);dummy.updateMatrix();clumps.setMatrixAt(i,dummy.matrix);color.setHSL(.22,.15,.55+random()*.3);clumps.setColorAt(i,color);}clumps.castShadow=true;clumps.receiveShadow=true;treeLeaves.add(clumps);
 for(let i=0;i<16;i++){const angle=i*2.4,r=2+random()*3.8;const a=p.clone().add(new V(0,3+random()*2,0)),b=p.clone().add(new V(Math.cos(angle)*r,7+random()*3,Math.sin(angle)*r));const branch=geometryAt(new THREE.CylinderGeometry(.05,.19,a.distanceTo(b),7),wood,a.clone().add(b).multiplyScalar(.5).toArray());branch.quaternion.setFromUnitVectors(new V(0,1,0),b.sub(a).normalize());}}

// The downloaded model is textured; normalize to metres and add a simple local rig.
const originalBounds=new THREE.Box3().setFromObject(gltf.scene);const originalHeight=originalBounds.max.y-originalBounds.min.y;
const modelScale=1.45/originalHeight;
let modelGeometries=[];
function smoothSeams(geometry){const p=geometry.attributes.position,idx=geometry.index,sums=new Map(),keys=[];
 for(let i=0;i<p.count;i++)keys.push(`${Math.round(p.getX(i)*1e5)},${Math.round(p.getY(i)*1e5)},${Math.round(p.getZ(i)*1e5)}`);
 const a=new V(),b=new V(),c=new V(),n=new V();const count=idx?idx.count:p.count;
 for(let t=0;t<count;t+=3){const ids=[0,1,2].map(k=>idx?idx.getX(t+k):t+k);a.fromBufferAttribute(p,ids[0]);b.fromBufferAttribute(p,ids[1]);c.fromBufferAttribute(p,ids[2]);n.crossVectors(b.sub(a),c.sub(a));for(const i of ids){if(!sums.has(keys[i]))sums.set(keys[i],new V());sums.get(keys[i]).add(n);}}
 const normals=new Float32Array(p.count*3);for(let i=0;i<p.count;i++)sums.get(keys[i]).clone().normalize().toArray(normals,i*3);geometry.setAttribute('normal',new THREE.BufferAttribute(normals,3));}
gltf.scene.updateMatrixWorld(true);
gltf.scene.traverse(child=>{if(!child.isMesh||child.geometry.attributes.position.count<20)return;const geo=child.geometry.clone();geo.applyMatrix4(child.matrixWorld);geo.translate(0,-originalBounds.min.y,0);geo.scale(modelScale,modelScale,modelScale);geo.computeVertexNormals();
 smoothSeams(geo);const material=child.material.clone();material.roughness=.85;material.metalness=0;material.side=THREE.FrontSide;material.flatShading=false;
 if(material.map){material.map.anisotropy=8;material.map.colorSpace=THREE.SRGBColorSpace;}
 // Coat recolouring is a shader approximation; source-photo crops remain available.
 if(geo.attributes.position.count>1000){cowNormal.flipY=false;material.normalMap=cowNormal;material.normalScale=new THREE.Vector2(.45,.45);}
 modelGeometries.push({geometry:geo,material});});
const mainGeo=modelGeometries.reduce((a,b)=>a.geometry.attributes.position.count>b.geometry.attributes.position.count?a:b).geometry;
const hoofMarkers=[];
for(const sx of [-1,1])for(const sz of [-1,1]){const pos=mainGeo.attributes.position;let candidates=[];for(let i=0;i<pos.count;i++){const x=pos.getX(i),y=pos.getY(i),z=pos.getZ(i);if(x*sx>0&&z*sz>.35)candidates.push([x,y,z]);}candidates.sort((a,b)=>a[1]-b[1]);const low=candidates.filter(p=>p[1]<candidates[0][1]+.015);hoofMarkers.push(new V(low.reduce((s,p)=>s+p[0],0)/low.length,low[0][1],low.reduce((s,p)=>s+p[2],0)/low.length));}
function rigGeometry(geo){const indices=new Uint16Array(geo.attributes.position.count*4),weights=new Float32Array(indices.length),p=geo.attributes.position;
 for(let i=0;i<p.count;i++){const x=p.getX(i),y=p.getY(i),z=p.getZ(i);let bone=0,w=0;if(y<.74&&Math.abs(z)>.33){bone=1+(x>=0?2:0)+(z>=0?1:0);w=1-THREE.MathUtils.smoothstep(y,.36,.74);}else if(z<-.6&&y>.72){bone=5;w=THREE.MathUtils.smoothstep(-z,.60,.9);}indices[i*4]=bone;indices[i*4+1]=0;weights[i*4]=w;weights[i*4+1]=1-w;}
 geo.setAttribute('skinIndex',new THREE.BufferAttribute(indices,4));geo.setAttribute('skinWeight',new THREE.BufferAttribute(weights,4));return geo;}
modelGeometries=modelGeometries.map(m=>({...m,geometry:rigGeometry(m.geometry)}));
for(const observation of config.cows){const root=new THREE.Group();root.position.fromArray(observation.position);root.rotation.y=observation.yaw+Math.PI; // Asset head points -Z.
 const meshes=[],skeletons=[];
 for(const asset of modelGeometries){const mesh=new THREE.SkinnedMesh(asset.geometry,asset.geometry.attributes.position.count>1000?coatMaterial(asset.material,observation.coat_color):asset.material.clone());const bones=Array.from({length:6},()=>new THREE.Bone());bones[5].position.set(0,1,-.65);for(let j=1;j<6;j++)bones[0].add(bones[j]);mesh.add(bones[0]);const skeleton=new THREE.Skeleton(bones);mesh.bind(skeleton);mesh.castShadow=true;mesh.receiveShadow=true;root.add(mesh);meshes.push(mesh);skeletons.push(skeleton);}
 scene.add(root);root.updateMatrixWorld(true);
 const contacts=[];for(let i=0;i<4;i++){const local=hoofMarkers[i].clone();const wp=root.localToWorld(local.clone());const g=terrain.sample(wp.x,wp.z);if(!g.valid)throw Error('Cow hoof crosses missing terrain: '+observation.sceneCowId);const offset=g.height-wp.y;for(const sk of skeletons)sk.bones[i+1].position.y=offset;contacts.push({local:local.toArray(),world:[wp.x,g.height,wp.z],adjustment_m:offset,error_m:0});}
 const label=document.createElement('button');label.className='cow-label';label.textContent=observation.sceneCowId;label.setAttribute('aria-label','Select cow '+observation.sceneCowId);$('#labels').append(label);
 const cow={...observation,root,meshes,skeletons,label,contacts,greetUntil:0};cows.push(cow);meshes.forEach(m=>m.userData.cow=cow);label.onclick=()=>selectCow(cow);
 const collider=world.createCollider(RAPIER.ColliderDesc.cuboid(.4,.7,.95).setTranslation(root.position.x,root.position.y+.7,root.position.z).setRotation({x:0,y:Math.sin(root.rotation.y/2),z:0,w:Math.cos(root.rotation.y/2)}));cow.collider=collider;
 hoofChecks.push({id:cow.sceneCowId,contacts});}

const coverImage=await new Promise((resolve,reject)=>{const i=new Image();i.onload=()=>resolve(i);i.onerror=reject;i.src='landcover.jpg';});
const coverCanvas=document.createElement('canvas');coverCanvas.width=512;coverCanvas.height=512;const coverContext=coverCanvas.getContext('2d',{willReadFrequently:true});coverContext.drawImage(coverImage,0,0);const cover=coverContext.getImageData(0,0,512,512).data;
function landAt(x,z){const i=Math.min(511,Math.max(0,Math.floor((x-MIN_X)/SPAN_X*512))),j=Math.min(511,Math.max(0,Math.floor((z-MIN_Z)/SPAN_Z*512)));const k=(j*512+i)*4;return [cover[k],cover[k+1],cover[k+2]];}
const grassGeo=new THREE.BufferGeometry();grassGeo.setAttribute('position',new THREE.Float32BufferAttribute([-.016,0,0,.016,0,0,-.011,.18,.018,.011,.18,.018,0,.38,.05],3));grassGeo.setAttribute('uv',new THREE.Float32BufferAttribute([0,0,1,0,0,.5,1,.5,.5,1],2));grassGeo.setIndex([0,1,2,1,3,2,2,3,4]);grassGeo.computeVertexNormals();
const grassMaterial=new THREE.MeshStandardMaterial({color:0xffffff,roughness:1,side:THREE.DoubleSide});
let grassShader;grassMaterial.onBeforeCompile=shader=>{grassShader=shader;shader.uniforms.uTime={value:0};shader.vertexShader=shader.vertexShader.replace('#include <common>','#include <common>\nuniform float uTime; varying float vBladeHeight;').replace('#include <begin_vertex>','#include <begin_vertex>\nvBladeHeight=uv.y; vec3 root=instanceMatrix[3].xyz; transformed.x += sin(uTime*1.5+root.x*.7+root.z*.6)*uv.y*uv.y*.055;');shader.fragmentShader=shader.fragmentShader.replace('#include <common>','#include <common>\nvarying float vBladeHeight;').replace('#include <color_fragment>','#include <color_fragment>\ndiffuseColor.rgb*=mix(.50,1.12,vBladeHeight);');};
const coverSettings=config.vegetation;
const grass=new THREE.InstancedMesh(grassGeo,grassMaterial,100000);grass.receiveShadow=true;grass.frustumCulled=false;scene.add(grass);let grassCentre=new V(999,0,999);
function updateGrass(force=false){const centre=mode==='walk'?player.translation():controls.target;if(!force&&Math.hypot(centre.x-grassCentre.x,centre.z-grassCentre.z)<5)return;grassCentre.set(centre.x,0,centre.z);let count=0;randomSeed=config.procedural_seeds.grass;
 for(let i=0;i<125000*coverSettings.density&&count<Math.min(100000,100000*coverSettings.density)&&coverSettings.type!=='bare';i++){const angle=random()*Math.PI*2,rad=Math.sqrt(random())*(mode==='walk'?24:Math.min(SPAN_X,SPAN_Z)*.45),x=centre.x+Math.cos(angle)*rad,z=centre.z+Math.sin(angle)*rad;if(x<MIN_X+2||x>MAX_X-2||z<MIN_Z+2||z>MAX_Z-2)continue;const rgb=landAt(x,z);if(rgb[1]<rgb[0]*1.03||rgb[1]<rgb[2]*1.07||rgb[1]<48)continue;const s=terrain.sample(x,z);if(!s.valid)continue;dummy.position.set(x,s.height-.012,z);dummy.rotation.set(0,random()*Math.PI*2,0);const size=(coverSettings.height_m/.38)*(.65+random()*.7);dummy.scale.set(.75+random()*.5,size,.75+random()*.5);dummy.updateMatrix();grass.setMatrixAt(count,dummy.matrix);color.setRGB(rgb[0]/255,rgb[1]/255,rgb[2]/255,THREE.SRGBColorSpace);color.lerp(new THREE.Color(0x6c813e),.35).multiplyScalar(.8+random()*.5);grass.setColorAt(count,color);count++;}grass.count=count;grass.instanceMatrix.needsUpdate=true;if(grass.instanceColor)grass.instanceColor.needsUpdate=true;}
updateGrass(true);
const selectionRing=new THREE.Mesh(new THREE.RingGeometry(1.3,1.36,64),new THREE.MeshBasicMaterial({color:0xd3c78d,side:THREE.DoubleSide,transparent:true,opacity:.85,depthWrite:false}));selectionRing.rotation.x=-Math.PI/2;selectionRing.visible=false;scene.add(selectionRing);
function frameForCard(){const size=renderer.getSize(new THREE.Vector2());if(mode==='walk'&&!$('#cow-card').hidden)camera.setViewOffset(size.x,size.y,size.x*(innerWidth<950?.18:.10),0,size.x,size.y);else camera.clearViewOffset();}
function selectCow(cow){selected=cow;$('#cow-card').hidden=false;$('#cow-id').textContent=cow.sceneCowId;$('#cow-photo').src=cow.source_crop;$('#cow-select').value=cow.sceneCowId;$('#heading-status').textContent=cow.heading_status.includes('ambiguous')?'Axis estimated · head uncertain':'Head direction reviewed';$('#source-link').href=cow.source_image;$('#coat-status').textContent=cow.coat_color;$('#coat-swatch').value=cow.coat_color;$('#review-link').href='review.html#'+cow.sceneCowId;for(const c of cows)c.label.classList.toggle('selected',c===cow);selectionRing.visible=true;selectionRing.position.copy(cow.root.position).add(new V(0,.025,0));if(mode==='overview')controls.target.copy(cow.root.position);frameForCard();}
for(const cow of cows){const option=document.createElement('option');option.value=option.textContent=cow.sceneCowId;$('#cow-select').append(option);}$('#cow-select').onchange=e=>{const cow=cows.find(c=>c.sceneCowId===e.target.value);if(cow)selectCow(cow);};
function spawnNear(cow,distance=7){const p=cow.root.position;for(let i=0;i<32;i++){const a=cow.root.rotation.y+Math.PI/2+i*Math.PI/16,x=p.x+Math.sin(a)*distance,z=p.z+Math.cos(a)*distance;const s=terrain.sample(x,z);if(!s.valid||x<MIN_X+5||x>MAX_X-5||z<MIN_Z+5||z>MAX_Z-5)continue;const ball=new RAPIER.Ball(.42);let blocked=false;
 for(let d=distance;d>=2.5;d-=.35){const qx=p.x+Math.sin(a)*d,qz=p.z+Math.cos(a)*d,ground=terrain.sample(qx,qz);if(!ground.valid||world.intersectionWithShape({x:qx,y:ground.height+.85,z:qz},{x:0,y:0,z:0,w:1},ball,undefined,undefined,playerCollider)){blocked=true;break;}}
 if(blocked)continue;player.setTranslation({x,y:s.height+.88,z},true);velocityY=0;yaw=Math.atan2(-(p.x-x),-(p.z-z));pitch=-.24;world.step();return;}throw Error('No valid nearby spawn');}
function enterWalk(cow=selected||cows[0],visit=false){try{if(cow){spawnNear(cow,visit?7:5);selectCow(cow);}else{let found=false;for(let ring=0;ring<60&&!found;ring++)for(let i=0;i<32&&!found;i++){const a=i*Math.PI/16,x=CENTRE_X+Math.sin(a)*ring*overviewScale/120,z=CENTRE_Z+Math.cos(a)*ring*overviewScale/120,s=terrain.sample(x,z);if(s.valid&&[[1,0],[-1,0],[0,1],[0,-1]].every(([dx,dz])=>terrain.sample(x+dx,z+dz).valid)){player.setTranslation({x,y:s.height+.88,z},true);velocityY=0;yaw=0;pitch=-.24;world.step();found=true;}}if(!found)throw Error('No walkable interior was found.');}}catch(e){toast(e.message);return;}mode='walk';controls.enabled=false;document.body.classList.add('walk-mode');$('#walk-help').hidden=false;$('#crosshair').hidden=false;$('#overview').classList.remove('active');$('#walking').classList.add('active');autoTarget=visit?cow:null;updateGrass(true);frameForCard();toast(visit?'Walking over. Drag to look around.':'You’re in the field. Use W A S D to walk; drag to look.');}
function overview(){mode='overview';autoTarget=null;keys.clear();controls.enabled=true;document.body.classList.remove('walk-mode');$('#walk-help').hidden=true;$('#crosshair').hidden=true;$('#overview').classList.add('active');$('#walking').classList.remove('active');camera.position.set(CENTRE_X+overviewScale*.55,overviewScale*.625,CENTRE_Z+overviewScale*.675);controls.target.set(CENTRE_X,1,CENTRE_Z-10);updateGrass(true);frameForCard();}
function movePlayer(dx,dz,dt=1/60){const current=player.translation();const safe=(x,z)=>[[0,0],[.35,0],[-.35,0],[0,.35],[0,-.35]].every(([a,b])=>terrain.sample(x+a,z+b).valid);if(!safe(current.x+dx,current.z+dz)){dx=0;dz=0;}velocityY=Math.max(-15,velocityY-9.81*dt);controller.computeColliderMovement(playerCollider,{x:dx,y:velocityY*dt,z:dz});const m=controller.computedMovement(),p=player.translation();const valid=safe(p.x+m.x,p.z+m.z);player.setNextKinematicTranslation({x:p.x+(valid?m.x:0),y:p.y+m.y,z:p.z+(valid?m.z:0)});if(controller.computedGrounded())velocityY=-.5;world.step();return m;}
let audioContext;function moo(){audioContext??=new AudioContext();audioContext.resume();const now=audioContext.currentTime,gain=audioContext.createGain();gain.connect(audioContext.destination);gain.gain.setValueAtTime(0,now);gain.gain.linearRampToValueAtTime(.10,now+.15);gain.gain.exponentialRampToValueAtTime(.001,now+1.25);const source=audioContext.createOscillator(),filter=audioContext.createBiquadFilter();source.type='sawtooth';source.frequency.setValueAtTime(102,now);source.frequency.exponentialRampToValueAtTime(70,now+1.2);filter.type='lowpass';filter.frequency.value=420;source.connect(filter).connect(gain);source.start(now);source.stop(now+1.3);}
let greetings=0;function greet(){if(!selected||mode!=='walk')return;const p=player.translation(),d=Math.hypot(p.x-selected.root.position.x,p.z-selected.root.position.z);if(d>3.5){toast('Walk a little closer to say hello.');return;}selected.greetUntil=performance.now()+2500;greetings++;moo();toast(`Hello, ${selected.sceneCowId}. Mooo!`);}
$('#start-walk').onclick=()=>enterWalk();$('#walking').onclick=()=>enterWalk();$('#overview').onclick=overview;$('#visit-cow').onclick=()=>enterWalk(selected,true);$('#greet').onclick=greet;
$('#close-card').onclick=()=>{$('#cow-card').hidden=true;selectionRing.visible=false;frameForCard();};
async function persistCow(patch){if(!selected)return;try{toast('Saving correction and rebuilding…');await savePatch(selected.sceneCowId,patch);location.reload();}catch(e){toast(e.message);}}
$('#flip-cow').onclick=()=>selected&&persistCow({axis_degrees:(selected.axis_degrees+180)%360,head_status:'reviewed'});
$('#save-coat').onclick=()=>persistCow({coat_color:$('#coat-swatch').value});
$('#labels-toggle').onchange=e=>$('#labels').hidden=!e.target.checked;$('#grass-toggle').onchange=e=>grass.visible=e.target.checked;
$('#info-button').onclick=()=>$('#info').showModal();$('#close-info').onclick=()=>$('#info').close();
const fit=config.camera.fit_rms_m,hold=config.camera.holdout_rms_m;
$('#accuracy-info').textContent=`Map alignment: fitting ${Number.isFinite(fit)?fit.toFixed(2)+' m RMS':'unreported'}; held-out ${Number.isFinite(hold)?hold.toFixed(2)+' m RMS':'unreported'}. ${config.camera.method}`;
$('#sources').replaceChildren(...config.attributions.map(a=>{const link=document.createElement('a');link.href=a.url;link.textContent=a.name+' ↗';link.target='_blank';link.rel='noopener';return link;}));
$('#limits').textContent=config.limits.join(' ');
$('#review-summary').textContent=surveyWorld?`${cows.length} displayed observations from ${config.photos.length} photos. All detections and head directions await review. Original crops are retained for every sighting.`:`${cows.length} displayed observations; ${config.detectionReview.filter(c=>c.status==='rejected').length} rejected. ${cows.filter(c=>c.status!=='accepted').length} await review. IDs refer to this photograph.`;
$('#grid-size').textContent=config.terrain.spacing+' m';
window.addEventListener('keydown',e=>{if(e.target.matches('input,textarea')||$('#info').open)return;if(['KeyW','KeyA','KeyS','KeyD','ArrowUp','ArrowDown','ArrowLeft','ArrowRight','Space'].includes(e.code))e.preventDefault();keys.add(e.code);if(e.code==='Escape')overview();if(e.code==='KeyE'&&!e.repeat)greet();});window.addEventListener('keyup',e=>keys.delete(e.code));window.addEventListener('blur',()=>keys.clear());
renderer.domElement.addEventListener('pointerdown',e=>{if(mode==='walk'){drag=true;lastPointer=[e.clientX,e.clientY];renderer.domElement.setPointerCapture(e.pointerId);}});renderer.domElement.addEventListener('pointerup',()=>{drag=false;});renderer.domElement.addEventListener('pointermove',e=>{if(!drag||mode!=='walk')return;yaw-=(e.clientX-lastPointer[0])*.004;pitch=THREE.MathUtils.clamp(pitch-(e.clientY-lastPointer[1])*.004,-1.25,1.25);lastPointer=[e.clientX,e.clientY];});
const raycaster=new THREE.Raycaster();renderer.domElement.addEventListener('click',e=>{if(mode!=='overview')return;raycaster.setFromCamera(new THREE.Vector2(e.clientX/innerWidth*2-1,1-e.clientY/innerHeight*2),camera);const hits=raycaster.intersectObjects(cows.flatMap(c=>c.meshes));if(hits[0])selectCow(hits[0].object.userData.cow);});
const mini=$('#minimap'),ctx=mini.getContext('2d');let mapImage=groundMap.image;
function drawMap(){ctx.drawImage(mapImage,0,0,360,360);ctx.fillStyle='#f7f2d6';for(const c of cows){const x=(c.root.position.x-MIN_X)/SPAN_X*360,z=(c.root.position.z-MIN_Z)/SPAN_Z*360;ctx.beginPath();ctx.arc(x,z,c===selected?5:2.8,0,Math.PI*2);ctx.fill();}if(mode==='walk'){const p=player.translation();ctx.fillStyle='#fff';ctx.strokeStyle='#294e3b';ctx.lineWidth=3;ctx.beginPath();ctx.arc((p.x-MIN_X)/SPAN_X*360,(p.z-MIN_Z)/SPAN_Z*360,5,0,Math.PI*2);ctx.fill();ctx.stroke();}}
mini.onclick=e=>{const r=mini.getBoundingClientRect(),x=MIN_X+(e.clientX-r.left)/r.width*SPAN_X,z=MIN_Z+(e.clientY-r.top)/r.height*SPAN_Z;if(!cows.length)return;const cow=cows.reduce((a,b)=>Math.hypot(b.root.position.x-x,b.root.position.z-z)<Math.hypot(a.root.position.x-x,a.root.position.z-z)?b:a);selectCow(cow);};
let frameTimes=[],lastFrame=performance.now(),accumulator=0,frame=0,benchmarking=false,checking=false;
function resize(){if(benchmarking)return;renderer.setSize(innerWidth,innerHeight);camera.aspect=innerWidth/innerHeight;camera.updateProjectionMatrix();frameForCard();}addEventListener('resize',resize);
function animate(now){requestAnimationFrame(animate);const elapsed=Math.min(.1,(now-lastFrame)/1000);frameTimes.push(now-lastFrame);if(frameTimes.length>1800)frameTimes.shift();lastFrame=now;accumulator=Math.min(.2,accumulator+elapsed);frame++;
 if(mode==='walk'&&!checking){while(accumulator>=1/60){let x=0,z=0;const speed=keys.has('ShiftLeft')?4.0:1.7;const forward=(keys.has('KeyW')||keys.has('ArrowUp')?1:0)-(keys.has('KeyS')||keys.has('ArrowDown')?1:0),side=(keys.has('KeyD')?1:0)-(keys.has('KeyA')?1:0);if(keys.has('ArrowLeft'))yaw+=.025;if(keys.has('ArrowRight'))yaw-=.025;x=(-Math.sin(yaw)*forward+Math.cos(yaw)*side)*speed/60;z=(-Math.cos(yaw)*forward-Math.sin(yaw)*side)*speed/60;
 if(autoTarget){const p=player.translation(),dx=autoTarget.root.position.x-p.x,dz=autoTarget.root.position.z-p.z,d=Math.hypot(dx,dz);if(d<2.7){autoTarget=null;toast('You’re close enough. Say hello.');}else{x=dx/d*1.8/60;z=dz/d*1.8/60;yaw=Math.atan2(-dx,-dz);}}
 movePlayer(x,z);accumulator-=1/60;}const p=player.translation();camera.position.set(p.x,p.y+.78,p.z);camera.rotation.order='YXZ';camera.rotation.set(pitch,yaw,0);if(frame%30===0)updateGrass();sunlight.position.set(p.x+sun.x*100,p.y+sun.y*100,p.z+sun.z*100);sunlight.target.position.set(p.x,p.y,p.z);
 }else{accumulator=0;if(mode==='overview')controls.update();}
 if(grassShader)grassShader.uniforms.uTime.value=now/1000;
 const labelRects=[];
 for(const cow of [...cows].sort((a,b)=>(a===selected?-1:b===selected?1:0))){for(const sk of cow.skeletons){const greeting=now<cow.greetUntil;sk.bones[5].rotation.y=greeting?Math.sin((cow.greetUntil-now)*.002)*.18:Math.sin(now*.0005+cow.candidate_index)*.025;}
 const p=cow.root.position.clone().add(new V(0,2.0,0)),d=camera.position.distanceTo(p);p.project(camera);const lx=(p.x*.5+.5)*innerWidth,ly=(-p.y*.5+.5)*innerHeight;const overlaps=labelRects.some(q=>Math.abs(q[0]-lx)<65&&Math.abs(q[1]-ly)<25);cow.label.hidden=p.z>1||p.z<0||Math.abs(p.x)>1||Math.abs(p.y)>1||(mode==='walk'&&d>50)||overlaps;if(!cow.label.hidden)labelRects.push([lx,ly]);cow.label.style.left=`${lx}px`;cow.label.style.top=`${ly}px`;
 }
 if(selected){const p=mode==='walk'?player.translation():camera.position,d=Math.hypot(p.x-selected.root.position.x,p.z-selected.root.position.z);$('#cow-distance').textContent=`${d.toFixed(1)} m`;$('#greet').disabled=mode!=='walk'||d>3.5;}
 if(frame%20===0){drawMap();const recent=frameTimes.slice(-90),fps=1000/(recent.reduce((a,b)=>a+b,0)/recent.length);$('#fps').textContent=`${fps.toFixed(0)} FPS · ${mode==='walk'?'eye height 1.63 m':'measured heights ×1'}`;if(mode==='walk'){const p=player.translation();$('#elevation').textContent=`${(terrain.sample(p.x,p.z).height+config.origin.altitude).toFixed(1)} m`;}}
 renderer.render(scene,camera);
}
requestAnimationFrame(animate);$('#loading').hidden=true;$('#cow-count').textContent=cows.length;world.step();
async function capture(name=mode==='walk'?(selected?'cow':'walking'):'overview'){renderer.render(scene,camera);if(surveyWorld){const a=document.createElement('a');a.download=config.scene_id+'-'+name+'.png';a.href=renderer.domElement.toDataURL('image/png');a.click();return;}const png=renderer.domElement.toDataURL('image/png').split(',')[1];await post('api/capture',{name,png});toast('Screenshot saved to this field’s evidence folder.');}
$('#capture').onclick=()=>capture().catch(e=>toast(e.message));
$('#checks').onclick=async()=>{if(checking||benchmarking)return;const button=$('#checks');button.disabled=true;toast('Checking terrain, hoof contacts, walking and 1080p performance…');const report={date:new Date().toISOString(),userAgent:navigator.userAgent,renderer:renderer.getContext().getParameter(renderer.getContext().RENDERER),terrainVertices:terrain.positions.length/3,terrainTriangles:terrain.indices.length/3,cows:cows.length,checks:{},manualInteractions:{greetings},limits:config.limits};
 try {checking=true;let maxError=0;randomSeed=9803;for(let i=0;i<500;i++){const x=MIN_X+2+random()*(SPAN_X-4),z=MIN_Z+2+random()*(SPAN_Z-4),s=terrain.sample(x,z);if(!s.valid)continue;const top=config.terrain.maxAltitude-config.origin.altitude+20,hit=world.castRay(new RAPIER.Ray({x,y:top,z},{x:0,y:-1,z:0}),1000,true,undefined,undefined,undefined,undefined,c=>c.handle===groundCollider.handle);if(!hit)throw Error('Terrain collider miss');maxError=Math.max(maxError,Math.abs(top-hit.timeOfImpact-s.height));}report.checks.renderColliderMaxError_m=maxError;if(maxError>.01)throw Error('Collider disagrees with rendered surface');
 let maxHoof=0;for(const c of cows){c.root.updateMatrixWorld(true);for(let i=0;i<4;i++){const marker=hoofMarkers[i].clone();marker.y+=c.skeletons[0].bones[i+1].position.y;const p=c.root.localToWorld(marker);maxHoof=Math.max(maxHoof,Math.abs(p.y-terrain.sample(p.x,p.z).height));}}report.checks.hoofContactMaxError_m=maxHoof;if(maxHoof>.03)throw Error('Hoof contact mismatch');
 const previous=player.translation();let groundGaps=[];let route=[];let stopped=false;for(const routeZ of [MIN_Z+SPAN_Z*.125,MIN_Z+SPAN_Z*.825]){const s=terrain.sample(MIN_X+SPAN_X*.15,routeZ);player.setTranslation({x:MIN_X+SPAN_X*.15,y:s.height+.89,z:routeZ},true);velocityY=0;world.step();for(let i=0;i<600;i++){movePlayer(1.7/60,0);const p=player.translation();if(i%60===0){route.push([p.x,p.y,p.z]);groundGaps.push(p.y-.85-terrain.sample(p.x,p.z).height);}}}
 player.setTranslation({x:MAX_X-2.5,y:terrain.sample(MAX_X-2.5,MIN_Z+SPAN_Z*.825).height+.89,z:MIN_Z+SPAN_Z*.825},true);velocityY=0;world.step();for(let i=0;i<150;i++)movePlayer(.04,0);stopped=player.translation().x<MAX_X-1.25;report.checks.boundaryStopsWalker=stopped;report.checks.walkingGroundGapRange_m=[Math.min(...groundGaps),Math.max(...groundGaps)];report.checks.walkingRouteSamples=route;if(!stopped||Math.min(...groundGaps)<-.05||Math.max(...groundGaps)>.2)throw Error('Walking contact check failed');player.setTranslation(previous,true);velocityY=0;world.step();checking=false;
 benchmarking=true;renderer.setSize(1920,1080,false);camera.aspect=1920/1080;camera.updateProjectionMatrix();frameForCard();await delay(1800);frameTimes=[];const begin=performance.now();await delay(10000);const samples=frameTimes.filter(v=>v>0);const sorted=[...samples].sort((a,b)=>a-b);const mean=samples.reduce((a,b)=>a+b,0)/samples.length;report.performance={width:1920,height:1080,pixelRatio:1,elapsed_ms:performance.now()-begin,frames:samples.length,averageFps:samples.length/((performance.now()-begin)/1000),p95Frame_ms:sorted[Math.floor(sorted.length*.95)],mode,grassInstances:grass.count,drawCalls:renderer.info.render.calls,triangles:renderer.info.render.triangles};report.passed=report.performance.averageFps>=30;await post('api/validation',{report});await capture(mode==='walk'?'walking':'overview');toast(`${report.passed?'Checks passed':'Performance target missed'} · ${report.performance.averageFps.toFixed(1)} FPS at 1920 × 1080. Report saved.`);
 }catch(e){report.passed=false;report.error=e.message;await post('api/validation',{report});toast('Check failed: '+e.message);console.error(e);}finally{checking=false;benchmarking=false;button.disabled=false;resize();}};

window.worldDemo={config,cows,terrain,world,player,playerCollider,groundCollider,selectCow,enterWalk,overview,movePlayer,greet,renderer,camera,get mode(){return mode},get greetings(){return greetings},get selected(){return selected}};
