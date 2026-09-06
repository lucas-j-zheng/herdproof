// Canonical grid: +X east, +Y up, +Z south. One scene unit is one metre.
// Each cell uses exactly these two triangles in rendering, sampling and Rapier.
export function makeTerrain(spec, heights) {
  const {width:w,height:h,spacing:s,minX,minZ}=spec;
  if(heights.length!==w*h || !heights.every(Number.isFinite)) throw Error('Invalid height grid');
  const positions=new Float32Array(w*h*3),uvs=new Float32Array(w*h*2),indices=new Uint32Array((w-1)*(h-1)*6);
  for(let j=0;j<h;j++) for(let i=0;i<w;i++) {
    const k=j*w+i;positions.set([minX+i*s,heights[k],minZ+j*s],k*3);
    uvs.set([i/(w-1),1-j/(h-1)],k*2);
  }
  let k=0;
  for(let j=0;j<h-1;j++) for(let i=0;i<w-1;i++) {
    const a=j*w+i,b=a+1,c=a+w,d=c+1;
    indices.set([a,c,b,b,c,d],k);k+=6;
  }
  function sample(x,z) {
    const col=(x-minX)/s,row=(z-minZ)/s;
    if(!Number.isFinite(col+row)||col<0||row<0||col>w-1||row>h-1) return {valid:false};
    const i=Math.min(w-2,Math.floor(col)),j=Math.min(h-2,Math.floor(row));
    const u=col-i,v=row-j,a=j*w+i,b=a+1,c=a+w,d=c+1;
    const first=u+v<=1;
    const y=first?heights[a]*(1-u-v)+heights[b]*u+heights[c]*v:heights[d]*(u+v-1)+heights[b]*(1-v)+heights[c]*(1-u);
    const dx=first?(heights[b]-heights[a])/s:(heights[d]-heights[c])/s;
    const dz=first?(heights[c]-heights[a])/s:(heights[d]-heights[b])/s;
    const len=Math.hypot(dx,1,dz);
    return {valid:true,height:y,normal:[-dx/len,1/len,-dz/len],triangle:(j*(w-1)+i)*2+(first?0:1)};
  }
  return {positions,indices,uvs,heights,spec,sample};
}
