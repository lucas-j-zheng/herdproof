export async function session(){
  const response=await fetch('api/review',{cache:'no-store'});
  if(!response.ok)throw Error('Editing requires the local review server. This scene can still be viewed as a static bundle.');
  return response.json();
}
export async function post(endpoint,payload={},state=null){
  state??=await session();
  const response=await fetch(endpoint,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...payload,token:state.token})});
  const result=await response.json();if(!response.ok)throw Error(result.error||'Operation failed');return result;
}
export async function savePatch(id,patch){
  const state=await session();state.review.observations[id]={...state.review.observations[id],...patch};
  await post('api/review',{review:state.review,expected_hash:state.hash},state);
  await post('api/build',{},state);
}
