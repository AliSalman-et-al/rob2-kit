"""Post-freeze extraction only; no model calls or repairs."""
import base64, hashlib, json, re
from pathlib import Path
R=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def write(n,x): (R/n).write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
def main():
 for n,h in json.loads((R/'answer-freeze.json').read_text()).items(): assert sha(R/n)==h
 rows=[json.loads(x) for x in (R/'events.jsonl').read_text().splitlines()]
 receipts=[];windows=[];images=[]
 for row in rows:
  i=row.get('item',{})
  if row.get('type')!='item.completed' or i.get('type')!='mcp_tool_call':continue
  result=i.get('result') or {};e=result.get('structured_content')
  if not isinstance(e,dict):
   e=next((json.loads(c['text']) for c in result.get('content',[]) if c.get('type')=='text' and c.get('text','').startswith('{')),None)
  receipts.append({'item':i['id'],'tool':i['tool'],'arguments':i.get('arguments'),'receipt':e,'error':i.get('error')})
  if i['tool']=='read_pages' and isinstance(e,dict):
   for p in e.get('data',{}).get('pages',[]):
    body=p.get('numbered_text','');ns=[int(x.split('|',1)[0]) for x in body.splitlines() if re.match(r'^\d+\|',x)]
    windows.append({**{k:p.get(k) for k in ['source_id','page']},'start_line':min(ns) if ns else None,'end_line':max(ns) if ns else None,'numbered_text':body,'sha256':hashlib.sha256(body.encode()).hexdigest()})
  for b in result.get('content',[]):
   if b.get('type')=='image':images.append({'tool':i['tool'],'arguments':i.get('arguments'),'sha256':hashlib.sha256(base64.b64decode(b['data'])).hexdigest(),'mime':b.get('mimeType')})
 write('native-receipts.json',receipts);write('delivered-source-windows.json',windows);write('native-image-identities.json',images)
 s=json.loads((R/'setup.json').read_text());m=json.loads((R/'manifest.json').read_text());sessions=list((Path(m['home'])/'sessions').rglob('*.jsonl'));assert len(sessions)==1
 session=[json.loads(x) for x in sessions[0].read_text().splitlines()];meta=next(r['payload'] for r in session if r['type']=='session_meta');base=meta['base_instructions'];base=base['text'] if isinstance(base,dict) else base
 assert base.strip()==(R/'native-instructions.md').read_text().strip()
 write('context-provenance.json',{'effective_instructions_match_frozen_generic_skill_references':True,'instruction_sha256':m['instruction_sha256'],'skill_sha256':m['skill_sha256'],'session_rollout_sha256':sha(sessions[0]),'fresh_context':True,'native_transport':'mcp-codex','source_availability_not_reading':True})
 p=R/'stderr.log';write('stderr-preservation.json',{'private_path':str(p),'sha256':sha(p),'bytes':p.stat().st_size,'reason':'CLI account metadata; preserved privately.'})
 print(json.dumps({'tools':len(receipts),'read_windows':len(windows),'images':len(images)}))
if __name__=='__main__': main()
