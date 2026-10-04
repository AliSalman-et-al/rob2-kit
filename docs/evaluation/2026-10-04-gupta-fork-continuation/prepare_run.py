"""Freeze availability preflight and exact supported resume launcher; no inference."""
from __future__ import annotations
import hashlib,json,sqlite3,subprocess
from pathlib import Path
R=Path(__file__).parent;ROOT=R.resolve().parents[2];D=ROOT.parent/'diagnostics/gupta-fork-continuation-20261004';OLD=ROOT.parent/'diagnostics/gupta-validation-fcd83d7'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
pf=json.loads((R/'preflight.json').read_text());assert pf['success'] and pf['recovered_latest_turn'];assert pf['response_metadata']['reasoningEffort']=='medium';assert pf['turns'][-1]['status']=='interrupted'
fork=next(p for p in (OLD/'home/sessions').rglob('*.jsonl') if pf['fork_id'] in p.name)
for line in fork.read_text().splitlines():
 row=json.loads(line)
 if row['type']=='session_meta':
  b=row['payload']['base_instructions'];b=b['text'] if isinstance(b,dict) else b
  assert b.strip()==(D/'rob2-assess/SKILL.md').read_text().strip()
  assert row['payload']['forked_from_id']==pf['source_session'];basehash=hashlib.sha256(b.encode()).hexdigest()
prompt='Continue this same approved assessment on its preserved fork from authoritative get_status and the installed production skill. Complete remaining Domains, inspect the ordinary Trial review and source support, make any scientifically justified ordinary revisions, then close and finalize if possible. Preserve assessment scope, uncertainty and counterevidence. Existing exact-scope approval remains inherited; stop at a genuine new researcher gate, scope change or experiment guard. Scientific judgments and any revisions are yours. Do not stop merely because a Domain or context page ended.'
(R/'prompt.txt').write_text(prompt)
# Complete captured projections are privately available; this packet is NOT sent to the model.
text='';windows=[]
with sqlite3.connect(f'file:{(D/"workspace/.rob2-kit/derivative.sqlite3").resolve()}?mode=ro',uri=True) as c:
 for source,page,body in c.execute('SELECT source_id,page,text FROM pages ORDER BY source_id,page'):
  lines=body.splitlines()
  if not lines:continue
  text+=f'Source {source}, physical page {page}\n';start=len(text.encode());block='\n'.join(f'{i}|{s}' for i,s in enumerate(lines,1));text+=block;end=len(text.encode());text+='\n\n';windows.append({'source_identity':source,'page':page,'start_line':1,'end_line':len(lines),'input_start_byte':start,'input_end_byte':end,'text_sha256':hashlib.sha256(block.encode()).hexdigest()})
packet=D/'availability-packet.txt';packet.write_text(text)
manifest={'research_question':'Can normal current-product continuation and Trial review preserve and repair factual attribution through production source interfaces?', 'input_sha256':sha(packet),'required_windows':[{k:w[k] for k in ['source_identity','page','start_line','end_line']} for w in windows],'supplied_windows':windows}
(R/'availability-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
config=json.loads((R/'fork-parameters.json').read_text())['config'];flags=[]
for k,v in config.items():flags+=['-c',k+'='+json.dumps(v,separators=(',',':'))]
# Structured JSON objects are valid TOML inline-table syntax only after key/value conversion.
import tomllib
# Emit leaf config values, avoiding object syntax ambiguity.
flags=[]
def leaves(prefix,obj):
 for k,v in obj.items():
  name=prefix+k
  if isinstance(v,dict):yield from leaves(name+'.',v)
  else:yield name,v
for key,value in leaves('',config):flags+=['-c',key+'='+json.dumps(value,separators=(',',':'))]
for i in range(1,len(flags),2):tomllib.loads(flags[i])
model_context=[];baseline_ids=[]
for line in fork.read_text().splitlines():
 row=json.loads(line);p=row.get('payload') or {}
 if row['type']=='token_usage_record':baseline_ids.append(p['response_id'])
m={'authorization':'Parent authorizes one separate experiment after supported fork success, at most two resumed turns; not original-run success', 'model':'gpt-6-luna','effort':'medium','fork_id':pf['fork_id'],'code_sha':pf['code_sha'],'transport':'mcp-codex','skill_sha256':sha(D/'rob2-assess/SKILL.md'),'effective_base_instructions_sha256':basehash,'source_original_session':pf['source_session'],'staging':str(D),'home':str(OLD/'home'),'cli_config_flags':flags,'prompt_sha256':sha(R/'prompt.txt'),'availability_manifest_sha256':sha(R/'availability-manifest.json'),'availability_packet_sha256':sha(packet),'availability_packet_not_model_input':True,'baseline_response_ids':baseline_ids,'baseline_fork_sha256':sha(fork),'limits':{'turns':2,'wall_seconds':600,'tools':35,'output_tokens':8000,'idle_seconds':120,'no_progress_boundaries':2,'identical_errors':2,'input_telemetry_only':True},'config_changes':'Recorded fork-only leaves; global and original isolated config unchanged'}
(R/'run-manifest.json').write_text(json.dumps(m,indent=2)+'\n')
print(json.dumps({'fork_instruction_verified':True,'private_captured_windows':len(windows),'source_packet_model_input':False,'config_leaf_parse':'passed'}))
