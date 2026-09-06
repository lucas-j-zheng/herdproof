import { createServer } from 'node:http';
import { readFile,writeFile,mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { resolve,extname,sep } from 'node:path';
const root=fileURLToPath(new URL('.',import.meta.url));
const mime={'.html':'text/html','.js':'text/javascript','.mjs':'text/javascript','.json':'application/json','.wasm':'application/wasm','.jpg':'image/jpeg','.png':'image/png','.glb':'model/gltf-binary','.css':'text/css'};
createServer(async(req,res)=>{
 try {
  const path=decodeURIComponent(new URL(req.url,'http://localhost').pathname);
  if(req.method==='POST' && path==='/api/validation') {
   let body='';for await(const chunk of req){body+=chunk;if(body.length>2e6)throw Error('Too large');}
   const report=JSON.parse(body);await mkdir(resolve(root,'evidence'),{recursive:true});
   await writeFile(resolve(root,'evidence/browser-validation.json'),JSON.stringify(report,null,2)+'\n');
   res.writeHead(200,{'Content-Type':'application/json'});res.end('{"saved":true}');return;
  }
  // Save the renderer's own pixels locally for reproducible screenshots.
  if(req.method==='POST' && /^\/api\/capture\/(overview|walking|cow)$/.test(path)){
   const chunks=[];let n=0;for await(const c of req){n+=c.length;if(n>25e6)throw Error('Too large');chunks.push(c);}
   await mkdir(resolve(root,'evidence'),{recursive:true});
   await writeFile(resolve(root,'evidence',path.split('/').at(-1)+'.png'),Buffer.concat(chunks));
   res.writeHead(200);res.end('saved');return;
  }
  const local=path==='/'?'index.html':path.slice(1);
  let file=resolve(root,local);
  if(!file.startsWith(root.endsWith(sep)?root:root+sep))throw Error('Invalid path');
  let body;try{body=await readFile(file);}catch{file=resolve(root,'public',local);if(!file.startsWith(resolve(root,'public')+sep))throw Error('Invalid path');body=await readFile(file);}
  res.writeHead(200,{'Content-Type':mime[extname(file)]||'application/octet-stream','Cache-Control':'no-cache','X-Content-Type-Options':'nosniff'});res.end(body);
 }catch{res.writeHead(404);res.end('Not found');}
}).listen(18770,'127.0.0.1',()=>console.log('Measured field: http://127.0.0.1:18770'));
