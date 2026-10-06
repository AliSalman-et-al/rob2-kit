"""Offline evidence audit after frozen response; no model or tool calls."""
from pathlib import Path
import hashlib,json,re,shutil,sqlite3
R=Path(__file__).resolve().parent;S=json.loads((R/'setup.json').read_text());M=json.loads((R/'manifest.json').read_text());D=Path(S['staging'])
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(n,x):(R/n).write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
for n,h in json.loads((R/'answer-freeze.json').read_text()).items():assert sha(R/n)==h
for p,h in {**json.loads((R/'original-preservation.json').read_text()),**json.loads((R/'protected-staging.json').read_text()),**M['existing_rollout_hashes']}.items():assert sha(Path(p))==h
rows=[json.loads(x) for x in (R/'events.jsonl').read_text().splitlines()]
receipts=[];windows=[];images=[]
for row in rows:
 i=row.get('item',{})
 if row['type']!='item.completed' or i.get('type')!='mcp_tool_call':continue
 result=i['result'];e=result.get('structured_content')
 if not isinstance(e,dict):e=next(json.loads(c['text']) for c in result.get('content',[]) if c.get('type')=='text' and c['text'].startswith('{'))
 receipts.append({'item':i['id'],'tool':i['tool'],'arguments':i['arguments'],'receipt':e})
 if i['tool']=='read_pages':
  for page in e['data']['pages']:
   body=page['numbered_text'];numbers=[int(line.split('|',1)[0]) for line in body.splitlines() if re.match(r'^\d+\|',line)]
   windows.append({'source_id':page['source_id'],'page':page['page'],'start_line':min(numbers),'end_line':max(numbers),'numbered_text_sha256':hashlib.sha256(body.encode()).hexdigest(),'characters':len(body),'numbered_text':body})
 for block in result.get('content',[]):
  if block.get('type')=='image':images.append({'sha256':hashlib.sha256(__import__('base64').b64decode(block['data'])).hexdigest(),'mime':block.get('mimeType')})
write('native-receipts.json',receipts);write('delivered-source-windows.json',windows);write('native-image-identities.json',{'model_render_calls':sum(x['tool']=='render_page' for x in receipts),'images':images,'visual_inspection':False,'operator_preflight_image_not_model_input':True})
review=[r for r in receipts if r['tool']=='review_trial'];first=review[0]['receipt']['data'];saved=json.loads((R/'private-scoring-units.json').read_text())
assert len(first['domain_findings'][0]['answers'])==3
assert [a['justification'] for a in first['domain_findings'][0]['answers']]==[a['justification'] for a in saved['answers']]
assert all(r['receipt']['head']['phase']=='finalized' and r['receipt']['head']['state_revision']==12 for r in receipts)
# Captured original support is checked offline, never supplied as a repair clue.
source='source_ec3fcba1a06e0ddceecbdc3cf37557a1a3b533e200d263de481c228cc373d510'
with sqlite3.connect(f'file:{Path(S["workspace"])/".rob2-kit/derivative.sqlite3"}?mode=ro',uri=True) as c:
 body=c.execute('SELECT text FROM pages WHERE source_id=? AND page=7',(source,)).fetchone()[0]
 lines=body.splitlines();actual='\n'.join(f'{n}|{lines[n-1]}' for n in range(85,95))
assert '13 of 86' in actual or ('13' in actual and '86' in actual and '94' in actual)
write('offline-count-support.json',{'source_id':source,'page':7,'start_line':85,'end_line':94,'numbered_text':actual,'text_sha256':hashlib.sha256(actual.encode()).hexdigest(),'delivered_to_model':False,'selected_original_citations_support_counts':False,'original_citations':json.loads((R.parents[0]/'2026-10-04-gupta-fork-continuation/audit.json').read_text())['measurement_count_citation']['selected']})
# Verify effective whole current skill, one new context, without publishing session metadata/account logs.
new=[p for p in (Path(M['home'])/'sessions').rglob('*.jsonl') if str(p) not in M['existing_rollout_hashes']];assert len(new)==1
session=[json.loads(x) for x in new[0].read_text().splitlines()];meta=next(r['payload'] for r in session if r['type']=='session_meta');base=meta['base_instructions'];base=base['text'] if isinstance(base,dict) else base
assert base.strip()==Path(S['skill']).read_text().strip()
write('context-provenance.json',{'new_session_id':meta['id'],'session_rollout_sha256':sha(new[0]),'effective_skill_matches_frozen_current_skill':True,'current_skill_sha256':M['skill_sha256'],'fresh_context':True,'inherited_original_or_fork_session_history':False,'native_transport':'mcp-codex','tool_allowlist':M['allowed_tools'],'prior_home_config_and_rollouts_unchanged':True})
# CLI stderr includes account metadata; preserve privately and commit its identity only.
stderr=R/'stderr.log';private=D/'native-cli-stderr.log';shutil.move(stderr,private)
write('stderr-preservation.json',{'private_path':str(private),'sha256':sha(private),'bytes':private.stat().st_size,'reason':'CLI telemetry contains account metadata; raw log is preserved privately, not published.'})
print('Frozen response, effective current skill, native receipts and immutable hashes verified offline.')
