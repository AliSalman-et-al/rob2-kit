"""Freeze one fresh native readonly review; no inference."""
from pathlib import Path
import hashlib,json,sqlite3,tomllib
R=Path(__file__).resolve().parent;S=json.loads((R/'setup.json').read_text());D=Path(S['staging']);W=Path(S['workspace']);ROOT=R.parents[2]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(n,x):(R/n).write_text(json.dumps(x,indent=2)+'\n')
assert json.loads((R/'preflight.json').read_text())['success']
prompt='Review the finalized gupta-2024 assessment read-only. Using the current review_trial view and ordinary source recovery, inspect all saved Domain 4 (domain:measurement) answers and their cited support. Report warranted factual or citation qualifications, distinguish direct support from inference, and retain uncertainty and justified risk judgments. Use authoritative status and the installed current skill. Do not reopen, save, approve, close, or finalize any assessment.'
(R/'prompt.txt').write_text(prompt+'\n')
(R/'private-criteria.md').write_text('Research question: Is current selected-review claim exposure usable for ordinary native evidence checking on immutable finalized state? Score all three D4 answers and all saved factual/citation claims, not only known failure. Primary endpoint: detects unsupported attribution of 13/86 versus 13/94 to original cited sources. Distinguish citation gap from false numeric claim: actual main-report physical page 7 lines 85–94 supports counts. Do not equate similar rates with measurement equivalence. Count unsupported alarms against qualified clinical-judgment inference and objective blinded measurement design; require source-qualified uncertainty. Score ordinary source retrieval, all selected-answer coverage, justified Low preservation, canonical immutability. No reference labels, page hint, clause hint, criteria or operator audit in input. One success is feasibility only: fresh context, changed task and obligations preclude causal packing or accuracy gain claims. Native image identity is recorded; text coverage alone does not establish visual inspection.\n')
# Whole saved claims, without selective clause extraction.
r=json.loads((R/'preflight-review_trial.json').read_text())
write('private-scoring-units.json',r['data']['domain_findings'][0])
text='';windows=[]
with sqlite3.connect(f'file:{W/".rob2-kit/derivative.sqlite3"}?mode=ro',uri=True) as c:
 for source,page,body in c.execute('SELECT source_id,page,text FROM pages ORDER BY source_id,page'):
  lines=body.splitlines()
  if not lines:continue
  text+=f'Source {source}, physical page {page}\n';start=len(text.encode());block='\n'.join(f'{i}|{line}' for i,line in enumerate(lines,1));text+=block;end=len(text.encode());text+='\n\n'
  windows.append({'source_identity':source,'page':page,'start_line':1,'end_line':len(lines),'input_start_byte':start,'input_end_byte':end,'text_sha256':hashlib.sha256(block.encode()).hexdigest()})
packet=D/'availability-packet.txt';packet.write_text(text)
write('availability-manifest.json',{'research_question':'Can current selected-review exposure support ordinary native factual/citation checking of all saved D4 claims?','input_sha256':sha(packet),'required_windows':[{k:w[k] for k in ('source_identity','page','start_line','end_line')} for w in windows],'supplied_windows':windows})
home=ROOT.parent/'diagnostics/d3-guidance-pair-20261003/new/home'
cfg=tomllib.loads((home/'config.toml').read_text());assert cfg['model']=='gpt-6-luna' and cfg['model_reasoning_effort']=='medium' and not cfg.get('mcp_servers')
config={'model_reasoning_effort':'medium','model_instructions_file':S['skill'],'web_search':'disabled','mcp_servers.rob2.command':S['python'],'mcp_servers.rob2.args':['-m','rob2_kit.interfaces.cli.app','mcp-codex'],'mcp_servers.rob2.required':True,'mcp_servers.rob2.default_tools_approval_mode':'approve','mcp_servers.rob2.startup_timeout_sec':60,'mcp_servers.rob2.tool_timeout_sec':90,'mcp_servers.rob2.enabled_tools':S['allowed_tools'],'mcp_servers.rob2.env.ROB2_WORKSPACE':str(W),'mcp_servers.rob2.env.PYTHONPATH':str(Path(S['code'])/'src'),'mcp_servers.rob2.env.PYTHONDONTWRITEBYTECODE':'1'}
flags=[]
for k,v in config.items():
 leaf=k+'='+json.dumps(v,separators=(',',':'));tomllib.loads(leaf);flags+=['-c',leaf]
write('manifest.json',{'authorization':'One bounded native read-only selected D4 review, not reopening or revision; no retry','fresh_context':True,'source_finalized_fork':'01a1046c-cdbe-7c81-8e2f-410015d6a089','model':'gpt-6-luna','effort':'medium','home':str(home),'config_sha256':sha(home/'config.toml'),'existing_rollout_hashes':{str(p):sha(p) for p in (home/'sessions').rglob('*.jsonl')},'flags':flags,'prompt_sha256':sha(R/'prompt.txt'),'private_criteria_sha256':sha(R/'private-criteria.md'),'scoring_units_sha256':sha(R/'private-scoring-units.json'),'availability_manifest_sha256':sha(R/'availability-manifest.json'),'availability_packet_sha256':sha(packet),'availability_packet_not_model_input':True,'captured_pages':len(windows),'skill_sha256':sha(Path(S['skill'])),'runner_sha256':sha(R/'run_once.py'),'limits':S['limits'],'allowed_tools':S['allowed_tools'],'source_inventory':json.loads((R/'preflight.json').read_text())['source_hashes_from_bundle']})
print('Frozen protocol and all-source availability manifest; no inference.')
