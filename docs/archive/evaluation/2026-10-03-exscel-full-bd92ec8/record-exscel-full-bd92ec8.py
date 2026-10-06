from pathlib import Path
import json,sqlite3,hashlib,shutil,sys
repo=Path.cwd();D=repo.parent/'diagnostics';root=D/'frozen-exscel-full-bd92ec8';prior=D/'frozen-exscel-bd92ec8';out=repo/'docs/evaluation/2026-10-03-exscel-full-bd92ec8';out.mkdir(exist_ok=True);sys.path.insert(0,str(D/'frozen-exscel-bd92ec8-code/src'))
from rob2_kit.application.finalization import verify_bundle
for n in ['manifest.json','prompt.txt','instructions.md','events.jsonl','run.json','durable-token-usage-records.json','approved-seed-state.json','approved-status.json','response.txt']:
 if (root/n).exists():shutil.copyfile(root/n,out/n)
for n in ['written-approval-authorization.json','cli-acknowledgment.stdout','cli-acknowledgment.stderr']:
 shutil.copyfile(prior/n,out/n)
for n in ['prepare-exscel-full-bd92ec8.py','run_exscel_full_bd92ec8.py','acknowledge-exscel.py','domain_probe_controls_telemetry.py']:
 shutil.copyfile(D/n,out/n)
shutil.copyfile(root/'home/config.toml',out/'cli-config.toml');shutil.copytree(root/'exported-skill',out/'installed-skill',dirs_exist_ok=True)
canon=prior/'workspace/.rob2-kit/canonical.sqlite3';before=hashlib.sha256(canon.read_bytes()).hexdigest()
with sqlite3.connect(f'file:{canon}?mode=ro',uri=True) as c:s=json.loads(c.execute('select payload from workflow_head').fetchone()[0])
(out/'final-state.json').write_text(json.dumps(s,indent=2)+'\n')
with sqlite3.connect(f'file:{prior}/workspace/.rob2-kit/derivative.sqlite3?mode=ro',uri=True) as c:
 c.row_factory=sqlite3.Row;reads=[dict(r) for r in c.execute('select * from page_reads')]
(out/'read-receipts.json').write_text(json.dumps(reads,indent=2)+'\n')
run=json.loads((root/'run.json').read_text());events=[json.loads(l) for l in (root/'events.jsonl').read_text().splitlines()];calls=[e['item'] for e in events if e.get('type')=='item.completed' and e.get('item',{}).get('type')=='mcp_tool_call']
(out/'domain-review-finalization-calls.json').write_text(json.dumps([i for i in calls if i['tool'] in ['save_domain_judgment','review_trial','close_trial','finalize_batch']],indent=2)+'\n')
model=[];direct=[];custom=[]
for p in (root/'home/sessions').rglob('*.jsonl'):
 for line in p.read_text().splitlines():
  r=json.loads(line);v=r.get('payload',{})
  if r['type']=='turn_context':assert (v['model'],v['effort'])==('gpt-6-luna','medium');model.append({k:v.get(k) for k in ['model','effort','turn_id']})
  if r['type']=='response_item' and v.get('type')=='function_call':direct.append({'name':v.get('name'),'call_id':v.get('call_id')})
  if r['type']=='response_item' and v.get('type')=='custom_tool_call':custom.append({'name':v.get('name'),'call_id':v.get('call_id')})
assert model;(out/'model-settings-and-call-count.json').write_text(json.dumps({'model':model,'direct':direct,'custom':custom},indent=2)+'\n')
artifact=s.get('artifact');verified=False;diagnostic={}
if s['phase']=='finalized' and isinstance(artifact,dict):
 bundle=prior/'workspace'/artifact['path'];verified=verify_bundle(bundle,diagnostic);assert verified,diagnostic;shutil.copyfile(bundle,out/bundle.name)
(out/'bundle-verification.json').write_text(json.dumps({'phase':s['phase'],'artifact':artifact,'verified':verified,'diagnostic':diagnostic},indent=2)+'\n');assert hashlib.sha256(canon.read_bytes()).hexdigest()==before
summary={'phase':s['phase'],'revision':s['revision'],'verified_bundle':verified,'domain_count':len(s.get('domain_records',{})),'stop_reason':run['stop_reason'],'elapsed_seconds':run['elapsed_seconds'],'usage':run['usage'],'input_plus_output_tokens':run['usage']['input_tokens']+run['usage']['output_tokens'],'uncached_input_tokens':run['uncached_input_tokens'],'MCP_calls':run['mcp_calls'],'custom_calls':len(custom),'total_visible_calls':run['mcp_calls']+len(custom),'construction_stats':run.get('proposal_construction_stats'),'approval_provenance':'Actual Ali explicit scope approval recorded through identity-checked delegated researcher CLI, not independent human adjudication','operator_repairs':0,'paid_continuation_invocations':1,'scientific_audit_pending':True,'dollar_cost':None}
(out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2));shutil.copyfile(Path(__file__),out/Path(__file__).name)
