from pathlib import Path
import hashlib,json,sqlite3,re
source=Path('/home/ali/Documents/Code/rob2-kit-benchmark/benchmark-luna6-medium-2026-10-01/cases/emperor-reduced/.rob2-kit')
with sqlite3.connect(f'file:{source/"canonical.sqlite3"}?mode=ro',uri=True) as c:state=json.loads(c.execute('select payload from workflow_head').fetchone()[0])
record=next(v for v in state['batch']['trials'][0]['sources'] if v['origin']=='registry')
with sqlite3.connect(f'file:{source/"derivative.sqlite3"}?mode=ro',uri=True) as c:pages=c.execute('select text from pages where source_id=? order by page',(record['id'],)).fetchall()
leaves={}
for line in '\n'.join(p[0] for p in pages).splitlines():
 path,value=line.split(': ',1);value=json.loads(value);leaves.setdefault(path,[]).append(value)
obj={}
for path,values in leaves.items():
 tokens=[]
 for key,index in re.findall(r'([A-Za-z_][A-Za-z_0-9]*)|\[(\d+)\]',path):tokens.append(key if key else int(index))
 node=obj
 for n,token in enumerate(tokens):
  value='\n'.join(values) if len(values)>1 and all(isinstance(v,str) for v in values) else values[0]
  if n==len(tokens)-1:
   if isinstance(node,list):
    while len(node)<=token:node.append(None)
   node[token]=value
  else:
   child=[] if isinstance(tokens[n+1],int) else {}
   if isinstance(node,list):
    while len(node)<=token:node.append(None)
    if node[token] is None:node[token]=child
   elif token not in node:node[token]=child
   node=node[token]
for ascii in (False,True):
 for indent,separators in ((2,None),(4,None),(None,None),(None,(',',':'))):
  raw=json.dumps(obj,ensure_ascii=ascii,indent=indent,separators=separators,sort_keys=True).encode()
  for suffix in (b'',b'\n'):
   candidate=raw+suffix
   if 'sha256:'+hashlib.sha256(candidate).hexdigest()==record['sha256']:
    dest=Path('/home/ali/Documents/Codex/2026-10-02/task-4/diagnostics/frozen-emperor-proposal-bef6a06/workspace/.rob2-kit/sources/emperor-reduced')/(record['id']+'.bin');dest.write_bytes(candidate)
    print('EXACT original registry bytes recovered',len(candidate),'hash',record['sha256'],'format',ascii,indent,separators,'newline',bool(suffix));raise SystemExit(0)
print('No exact-byte reconstruction. Do not use reconstructed bytes.');raise SystemExit(1)
