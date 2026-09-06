// One metric triangle convention for rendering, collision and terrain contact.
export function makeTerrain(spec, heights, validity = null) {
  const {width:w,height:h,spacing:s,minX,minZ}=spec;
  if(!Number.isInteger(w)||!Number.isInteger(h)||w<2||h<2||!Number.isFinite(s)||s<=0||!Number.isFinite(minX+minZ))throw Error('Invalid terrain dimensions');
  if(heights.length!==w*h||!heights.every(Number.isFinite)||validity&&validity.length!==w*h)throw Error('Invalid height grid');
  const valid=validity||new Uint8Array(w*h).fill(1);
  const positions=new Float32Array(w*h*3),uvs=new Float32Array(w*h*2),index=[];
  for(let j=0;j<h;j++)for(let i=0;i<w;i++){const k=j*w+i;positions.set([minX+i*s,heights[k],minZ+j*s],k*3);uvs.set([i/(w-1),1-j/(h-1)],k*2);}
  for(let j=0;j<h-1;j++)for(let i=0;i<w-1;i++){const a=j*w+i,b=a+1,c=a+w,d=c+1;if(valid[a]&&valid[b]&&valid[c])index.push(a,c,b);if(valid[d]&&valid[b]&&valid[c])index.push(b,c,d);}
  const indices=new Uint32Array(index);
  function sample(x,z){
    const col=(x-minX)/s,row=(z-minZ)/s;
    if(!Number.isFinite(col+row)||col<0||row<0||col>w-1||row>h-1)return {valid:false};
    const i=Math.min(w-2,Math.floor(col)),j=Math.min(h-2,Math.floor(row)),u=col-i,v=row-j,a=j*w+i,b=a+1,c=a+w,d=c+1,first=u+v<=1;
    if(first?!(valid[a]&&valid[b]&&valid[c]):!(valid[d]&&valid[b]&&valid[c]))return {valid:false};
    const y=first?heights[a]*(1-u-v)+heights[b]*u+heights[c]*v:heights[d]*(u+v-1)+heights[b]*(1-v)+heights[c]*(1-u);
    const dx=first?(heights[b]-heights[a])/s:(heights[d]-heights[c])/s,dz=first?(heights[c]-heights[a])/s:(heights[d]-heights[b])/s,len=Math.hypot(dx,1,dz);
    return {valid:true,height:y,normal:[-dx/len,1/len,-dz/len],triangle:(j*(w-1)+i)*2+(first?0:1)};
  }
  return {positions,indices,uvs,heights,valid,spec,sample};
}
