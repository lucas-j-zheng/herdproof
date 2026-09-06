import { cp, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = fileURLToPath(new URL('../', import.meta.url));
const source = path.join(root, 'dist/client');
const output = path.join(root, '.vercel/output');
const html = await readFile(path.join(source, 'index.html'), 'utf8');
if (!html.includes('HerdProof')) throw new Error('Build the HerdProof website before packaging.');
await rm(output, { recursive: true, force: true });
await mkdir(output, { recursive: true });
await cp(source, path.join(output, 'static'), { recursive: true });
await writeFile(path.join(output, 'config.json'), JSON.stringify({ version: 3 }, null, 2) + '\n');
console.log('Prepared the static website for Vercel.');
