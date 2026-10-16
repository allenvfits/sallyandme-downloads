import assert from 'node:assert/strict';
import {mkdir,writeFile,statfs} from 'node:fs/promises';
import {createWriteStream} from 'node:fs';
import {createHash,verify} from 'node:crypto';
import {Readable,Transform} from 'node:stream';
import {pipeline} from 'node:stream/promises';
const repo='allenvfits/sallyandme-downloads';assert.equal(process.env.GITHUB_REPOSITORY,repo);
const root=process.env.RUNNER_TEMP+'/sally-plan',base=root+'/base',nativeDir=root+'/native';await mkdir(base,{recursive:true});await mkdir(nativeDir);
const envelope=JSON.parse(process.env.RELEASE_RECORD),native=JSON.parse(process.env.NATIVE_RECORD);
const key='-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEA9YQCgwvqVKxVnOFOf4nlYCL1nj9Xgm5S73aN0VbXpXY=\n-----END PUBLIC KEY-----\n';
assert.equal(envelope.algorithm,'Ed25519');assert.ok(verify(null,Buffer.from(envelope.payload,'base64'),key,Buffer.from(envelope.signature,'base64')));
const m=JSON.parse(Buffer.from(envelope.payload,'base64'));assert.equal(m.edition,'complete');assert.equal(m.applicationId,'studio.sallyandme.desktop');assert.equal(m.source.commit,'fdb0007aa60abad85eb8a541becebfd62fddd4b9');
assert.equal(native.status,'passed');assert.equal(native.sha256,'21743fb8de76f1c6fe596b78fc89b1839edc86887c9933ee3a3ace2ba64cbd85');
const headers={Authorization:'Bearer '+process.env.GH_TOKEN,Accept:'application/vnd.github+json'};
async function api(path){const r=await fetch('https://api.github.com/repos/'+repo+path,{headers,redirect:'error'});assert.equal(r.status,200);return r.json();}
const release=await api('/releases/415071552');assert.equal(release.draft,true);assert.equal(release.tag_name,'complete-0.13.1-'+m.packageManifestSha256);
const assets=await api('/releases/415071552/assets'),rows=[{path:'SallyAndMe-Setup-0.13.1.exe',bytes:native.bytes,sha256:native.sha256},...m.parts],files=[];
const disk=await statfs(root);assert.ok(disk.bavail*disk.bsize>m.archive.bytes+native.bytes+1024**3,'Insufficient isolated runner storage');
for(const row of rows){
 assert.match(row.path,/^SallyAndMe-(?:Setup-0\.13\.1\.exe|0\.13\.0\.zip\.\d{3})$/);assert.ok(row.bytes>0&&row.bytes<2*1024**3);
 const asset=assets.find(a=>a.name===row.path);assert.ok(asset);assert.equal(asset.state,'uploaded');assert.equal(asset.size,row.bytes);assert.equal(asset.digest,'sha256:'+row.sha256);
 let response=await fetch('https://api.github.com/repos/'+repo+'/releases/assets/'+asset.id,{headers:{...headers,Accept:'application/octet-stream'},redirect:'manual',signal:AbortSignal.timeout(1200000)});
 if(response.status===302){const u=new URL(response.headers.get('location'));assert.equal(u.protocol,'https:');assert.ok(u.hostname.endsWith('.githubusercontent.com')||u.hostname.endsWith('.blob.core.windows.net'));response=await fetch(u,{redirect:'error',signal:AbortSignal.timeout(1200000)});}
 assert.equal(response.status,200);const hash=createHash('sha256');let bytes=0;
 const counter=new Transform({transform(chunk,_encoding,callback){bytes+=chunk.length;if(bytes>row.bytes)return callback(Error('Hosted source exceeds pinned size'));hash.update(chunk);callback(null,chunk);}});
 await pipeline(Readable.fromWeb(response.body),counter,createWriteStream((row.path.endsWith('.exe')?nativeDir:base)+'/'+row.path,{flags:'wx'}));
 assert.equal(bytes,row.bytes);assert.equal(hash.digest('hex'),row.sha256);files.push({...row,url:asset.browser_download_url});console.log('Verified hosted input: '+row.path);
}
await writeFile(base+'/candidate.json',JSON.stringify(m));await writeFile(nativeDir+'/installer-signature.json',JSON.stringify(native));
await writeFile(root+'/hosting.json',JSON.stringify({status:'verified-private-components',releaseId:415071552,archiveSha256:m.archive.sha256,files,nativeInstaller:files[0]}));
