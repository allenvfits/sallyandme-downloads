"""Create and verify an exact, seekable full ZIP delivery without duplicating 6 GB.
The server sends these pinned bytes as ONE ordinary ZIP; no customer assembly.
"""
import base64,bisect,hashlib,io,json,zipfile
from pathlib import Path
import argparse,re,sys,importlib.util
parser=argparse.ArgumentParser(description='Verify one Complete-edition ZIP from exact local signed release bytes, without making another 11 GB copy.')
parser.add_argument('--base',type=Path,required=True)
parser.add_argument('--native',type=Path,required=True)
parser.add_argument('--hosting',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
OLD=args.base.resolve();SIGN=args.native.resolve()
if args.output.exists():raise RuntimeError('Existing plan preserved')
def h(b):return hashlib.sha256(b).hexdigest()
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
old=read(OLD/'candidate.json');pub=read(args.hosting)
assert old['edition']=='complete' and old['buildKind']=='release' and not old['source']['dirty']
assert old['source']['commit']=='fdb0007aa60abad85eb8a541becebfd62fddd4b9'
assert pub['status'] in ('verified','verified-private-components') and pub['archiveSha256']==old['archive']['sha256']
assert len({f['path'] for f in pub['files']})==len(pub['files'])
for row in old['parts']:
    hosted=next(f for f in pub['files'] if f['path']==row['path'])
    assert hosted['bytes']==row['bytes'] and hosted['sha256']==row['sha256']
    assert re.fullmatch(r'https://github.com/allenvfits/sallyandme-downloads/releases/download/[^/]+/[^/]+',hosted['url'])
sig=read(SIGN/'installer-signature.json');assert sig['status']=='passed'
installer={'path':sig['file'],'bytes':sig['bytes'],'sha256':sig['sha256']}
installer['url']=pub['nativeInstaller']['url']
assert pub['nativeInstaller']['bytes']==installer['bytes'] and pub['nativeInstaller']['sha256']==installer['sha256']
assert re.fullmatch(r'https://github.com/allenvfits/sallyandme-downloads/releases/download/[^/]+/[^/]+',installer['url'])
def open_source(path):return Path(path).open('rb')
class Writer:
 def __init__(self):self.pos=0;self.digest=hashlib.sha256();self.rows=[];self.pending=bytearray();self.asset=None;self.local=[]
 def tell(self):return self.pos
 def flush(self):pass
 def write(self,b):
  self.digest.update(b);self.pos+=len(b)
  if self.asset:self.asset[1].update(b);self.asset[2]+=len(b)
  else:self.pending.extend(b)
  return len(b)
 def inline(self):
  if self.pending:
   b=bytes(self.pending);self.rows.append({'inline':base64.b64encode(b).decode(),'bytes':len(b),'sha256':h(b)});self.local.append(None);self.pending.clear()
 def begin(self,row,path):self.inline();self.asset=[row,hashlib.sha256(),0,path]
 def end(self):
  row,digest,size,path=self.asset;assert size==row['bytes'] and digest.hexdigest()==row['sha256'];self.rows.append(row);self.local.append(str(path));self.asset=None
w=Writer()
with zipfile.ZipFile(w,'w',compression=zipfile.ZIP_STORED,allowZip64=True) as z:
 for name,rows,size in [('Install SallyAndMe.exe',[(installer,SIGN/installer['path'])],installer['bytes']),('Files/offline.zip',[(next(f for f in pub['files'] if f['path']==r['path']),OLD/r['path']) for r in old['parts']],old['archive']['bytes'])]:
  info=zipfile.ZipInfo(name,date_time=(2026,10,16,0,0,0));info.file_size=size;info.compress_type=zipfile.ZIP_STORED
  with z.open(info,'w',force_zip64=size>2**31) as entry:
   for row,path in rows:
    w.begin(row,path)
    with open_source(path) as f:
     for chunk in iter(lambda:f.read(1024*1024),b''):entry.write(chunk)
    w.end()
  print('Verified content: '+name,flush=True)
 z.writestr('READ ME FIRST.txt','SallyAndMe Complete for Windows\r\n\r\n1. Right-click the downloaded ZIP and choose Extract All.\r\n2. Open Install SallyAndMe.exe. Check the verified publisher is WORKFLOWOS LLC.\r\n3. Use the SallyAndMe desktop icon or Start menu entry.\r\n\r\nThis one download includes the local AI models and offline Windows runtimes.\r\nKeep Files beside the installer while installing. No separate downloads are required.\r\nSign in and activate this computer with your purchased license or free access.\r\nInitial account verification and activation need internet.\r\nExisting memories, account records, models and customer files are preserved.\r\n\r\nWindows 11 x64 and 32 GB RAM recommended. Allow 28 GB free after downloading\r\nfor extraction and installation, plus room for your files and training.\r\nMicrosoft certification and independent second-PC acceptance remain pending.\r\nIncludes Qwen everyday chat and optional DeepSeek reasoning. Models run as selected by Sally; simultaneous use depends on available memory.\r\nAI answers need review. Music generation is not included in this build.\r\n\r\nSupport: contact@vonncore.com\r\nWebsite: https://sallyandme.studio\r\n')
w.inline()
class Reader(io.RawIOBase):
 def __init__(self):self.position=0;self.starts=[];offset=0;self.files={}
 def initialize(self):
  offset=0
  for row in w.rows:self.starts.append(offset);offset+=row['bytes']
  return self
 def seekable(self):return True
 def readable(self):return True
 def tell(self):return self.position
 def seek(self,n,whence=0):self.position=n if whence==0 else self.position+n if whence==1 else w.pos+n;return self.position
 def read(self,n=-1):
  n=min(w.pos-self.position,n if n>=0 else w.pos);out=[]
  while n:
   i=bisect.bisect_right(self.starts,self.position)-1;row=w.rows[i];offset=self.position-self.starts[i];amount=min(n,row['bytes']-offset)
   if 'inline' in row:b=base64.b64decode(row['inline'])[offset:offset+amount]
   else:
    if i not in self.files:self.files[i]=open_source(w.local[i])
    f=self.files[i];f.seek(offset);b=f.read(amount)
   if len(b)!=amount:raise IOError('Truncated source')
   out.append(b);self.position+=amount;n-=amount
  return b''.join(out)
 def close(self):
  for f in self.files.values():f.close()
  super().close()
with Reader().initialize() as reader,zipfile.ZipFile(reader) as z:
 assert z.namelist()==['Install SallyAndMe.exe','Files/offline.zip','READ ME FIRST.txt'];assert z.testzip() is None
 assert z.getinfo('Files/offline.zip').file_size==old['archive']['bytes']
plan={'edition':'complete','sourceCommit':old['source']['commit'],'archive':{'path':'SallyAndMe-Complete-Windows-0.13.1.zip','bytes':w.pos,'sha256':w.digest.hexdigest()},'installer':installer,'segments':w.rows,'verification':{'status':'passed','zip64':True,'crc':'passed','fileList':'passed','baseArchiveSha256':old['archive']['sha256'],'files':3},'localSources':w.local}
with args.output.open('x',encoding='utf8') as f:json.dump(plan,f,indent=2)
print(json.dumps({'archive':plan['archive'],'zipEntries':3,'verified':'all original bytes and full ZIP CRC','customerDownloads':1}),flush=True)
