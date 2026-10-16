"""Private staging of one hash-pinned Sally build. Never publishes a release."""
import concurrent.futures,hashlib,http.client,json,os,re,sys,time,urllib.request,urllib.parse,zipfile
from pathlib import Path
ROOT=Path(os.environ['RUNNER_TEMP'])/'sally-transfer';ROOT.mkdir(exist_ok=True)
REPO='allenvfits/sallyandme-downloads';RELEASE='415071552'
assert os.environ['GITHUB_REPOSITORY']==REPO
def api(path,method='GET'):
    request=urllib.request.Request('https://api.github.com/repos/'+REPO+path,method=method,headers={'Authorization':'Bearer '+os.environ['GH_TOKEN'],'Accept':'application/vnd.github+json','User-Agent':'Sally-private-transfer'})
    with urllib.request.urlopen(request,timeout=60) as response:return json.load(response) if response.status!=204 else None
def digest(path):
    with path.open('rb') as file:return hashlib.file_digest(file,'sha256').hexdigest()
if sys.argv[1]=='prepare':
    url=urllib.parse.urlsplit(os.environ['ARTIFACT_URL'])
    assert url.scheme=='https' and not url.username and (url.hostname.endswith('.blob.core.windows.net') or url.hostname.endswith('.actions.githubusercontent.com'))
    expected=int(os.environ['ARTIFACT_BYTES']);assert 0<expected<20*1024**3
    assert re.fullmatch('[a-f0-9]{64}',os.environ['ARTIFACT_SHA256'])
    with urllib.request.urlopen(urllib.request.Request(os.environ['ARTIFACT_URL'],method='HEAD'),timeout=60) as response:
        assert response.status==200 and int(response.headers['Content-Length'])==expected
        etag=response.headers['ETag'];assert etag
    with (ROOT/'candidate.zip').open('xb') as output:output.truncate(expected)
    chunk_size=64*1024**2
    def download_range(start):
        end=min(expected,start+chunk_size)-1
        for attempt in range(3):
            try:
                request=urllib.request.Request(os.environ['ARTIFACT_URL'],headers={'Range':f'bytes={start}-{end}','If-Match':etag,'Accept-Encoding':'identity'})
                with urllib.request.urlopen(request,timeout=120) as response:
                    assert response.status==206 and response.headers['Content-Range']==f'bytes {start}-{end}/{expected}' and response.headers['ETag']==etag
                    content=response.read(end-start+2)
                    assert len(content)==end-start+1,'Truncated artifact range'
                with (ROOT/'candidate.zip').open('r+b') as output:output.seek(start);output.write(content)
                return len(content)
            except Exception:
                if attempt==2:raise RuntimeError(f'Artifact range {start}-{end} failed after three attempts') from None
                time.sleep(attempt+1)
    total=0
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        for index,size in enumerate(pool.map(download_range,range(0,expected,chunk_size))):
            total+=size
            if index%16==0:print(f'Verified transfer ranges: {total}/{expected} bytes',flush=True)
    actual=digest(ROOT/'candidate.zip')
    receipt={'expectedBytes':expected,'actualBytes':total,'expectedSha256':os.environ['ARTIFACT_SHA256'],'actualSha256':actual,'status':'passed' if total==expected and actual==os.environ['ARTIFACT_SHA256'] else 'failed'}
    (ROOT/'artifact-transfer.json').write_text(json.dumps(receipt,indent=2));print(json.dumps(receipt),flush=True)
    assert receipt['status']=='passed','Entire artifact size/hash mismatch; see exact diagnostic receipt'
    with zipfile.ZipFile(ROOT/'candidate.zip') as archive:
        assert archive.testzip() is None
        for source,target in [('base/candidate.json','candidate.json'),('base/release.json','release.json'),('installer-signature.json','native.json')]:
            assert archive.getinfo(source).file_size<1000000
            (ROOT/target).write_bytes(archive.read(source))
    print('Entire original CI artifact SHA-256 and ZIP CRC verified.')
elif sys.argv[1]=='stage':
    assert (ROOT/'envelope-verified').read_text()=='verified'
    m=json.loads((ROOT/'candidate.json').read_text(encoding='utf-8-sig'));native=json.loads((ROOT/'native.json').read_text(encoding='utf-8-sig'))
    assert m['edition']=='complete' and m['source']['commit']=='fdb0007aa60abad85eb8a541becebfd62fddd4b9'
    release=api('/releases/'+RELEASE)
    assert release['draft'] and release['tag_name']=='complete-0.13.1-'+m['packageManifestSha256']
    existing=api('/releases/'+RELEASE+'/assets');rows=[{'path':'SallyAndMe-Setup-0.13.1.exe','bytes':native['bytes'],'sha256':native['sha256']},m['installer']]+m['parts'];results=[];removed=[]
    with zipfile.ZipFile(ROOT/'candidate.zip') as archive:
        for row in rows:
            assert re.fullmatch(r'SallyAndMe-(?:Setup-0\.13\.[01]\.exe|0\.13\.0\.zip\.\d{3})',row['path']) and 0<row['bytes']<2*1024**3
            asset=next((a for a in existing if a['name']==row['path']),None)
            if asset and asset['state']=='starter' and asset['digest'] is None:
                removed.append({'id':asset['id'],'name':asset['name'],'state':asset['state']})
                (ROOT/'removed-incomplete.json').write_text(json.dumps(removed,indent=2))
                api('/releases/assets/'+str(asset['id']),'DELETE');asset=None
            if not asset:
                member=('' if row['path']=='SallyAndMe-Setup-0.13.1.exe' else 'base/')+row['path']
                info=archive.getinfo(member);assert info.file_size==row['bytes']
                connection=http.client.HTTPSConnection('uploads.github.com',timeout=1200)
                connection.putrequest('POST','/repos/'+REPO+'/releases/'+RELEASE+'/assets?name='+urllib.parse.quote(row['path']))
                for key,value in {'Authorization':'Bearer '+os.environ['GH_TOKEN'],'Accept':'application/vnd.github+json','Content-Type':'application/octet-stream','Content-Length':str(row['bytes']),'User-Agent':'Sally-private-transfer'}.items():connection.putheader(key,value)
                connection.endheaders();hash=hashlib.sha256();total=0
                with archive.open(info) as source:
                    for chunk in iter(lambda:source.read(4*1024**2),b''):connection.send(chunk);hash.update(chunk);total+=len(chunk)
                assert total==row['bytes'] and hash.hexdigest()==row['sha256']
                response=connection.getresponse();assert response.status==201,'Private component upload failed';asset=json.load(response);connection.close()
            assert asset['state']=='uploaded' and asset['size']==row['bytes'] and asset['digest']=='sha256:'+row['sha256']
            results.append({**row,'url':asset['browser_download_url'],'assetId':asset['id']});print('Verified private component: '+row['path'],flush=True)
    assert api('/releases/'+RELEASE)['draft']
    (ROOT/'hosting.json').write_text(json.dumps({'status':'verified-private-components','releaseId':int(RELEASE),'tag':release['tag_name'],'sourceCommit':m['source']['commit'],'archiveSha256':m['archive']['sha256'],'files':results,'nativeInstaller':results[0],'artifactSha256':os.environ['ARTIFACT_SHA256'],'scope':'Private components only; no public publication or customer enablement.'},indent=2))
else:raise ValueError('Unknown operation')
