import * as THREE from 'three';

// Immutable geometry/maps are shared; color uniforms belong to one cow material.
export function coatMaterial(base, color) {
  const material=base.clone();
  material.userData.coatColor=new THREE.Color(color);
  material.onBeforeCompile=shader=>{
    shader.uniforms.cowCoatColor={value:material.userData.coatColor};
    shader.vertexShader=shader.vertexShader.replace('#include <common>','#include <common>\nvarying vec3 vCoatPosition;')
      .replace('#include <begin_vertex>','#include <begin_vertex>\nvCoatPosition=position;');
    shader.fragmentShader=shader.fragmentShader.replace('#include <common>','#include <common>\nuniform vec3 cowCoatColor; varying vec3 vCoatPosition;')
      .replace('#include <map_fragment>',`#include <map_fragment>
        float lum=dot(diffuseColor.rgb,vec3(.2126,.7152,.0722));
        float coat=smoothstep(.16,.34,vCoatPosition.y)*(1.0-smoothstep(.60,.94,-vCoatPosition.z));
        vec3 neutralDetail=vec3(.82+.18*sqrt(max(lum,0.0)));
        diffuseColor.rgb=mix(diffuseColor.rgb,cowCoatColor*neutralDetail,coat);`);
  };
  material.customProgramCacheKey=()=> 'per-cow-neutral-coat-v2';
  return material;
}
