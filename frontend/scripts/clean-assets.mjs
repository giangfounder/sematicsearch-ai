import {readFile,readdir,unlink} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
const root=fileURLToPath(new URL('../../app/static/',import.meta.url));
const manifest=JSON.parse(await readFile(path.join(root,'.vite/manifest.json'),'utf8'));
const used=new Set(Object.values(manifest).flatMap(entry=>[entry.file,...(entry.css||[]),...(entry.assets||[])]));
// This directory contains only Vite output. Preserve all unknown filenames.
for(const entry of await readdir(path.join(root,'assets'),{withFileTypes:true})) {
  if(entry.isFile() && /^(?:index-|be-vietnam-pro-|outfit-).+\.(js|css|woff2?)$/.test(entry.name) && !used.has('assets/'+entry.name)) await unlink(path.join(root,'assets',entry.name));
}
