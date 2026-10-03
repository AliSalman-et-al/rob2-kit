from pathlib import Path
import json,sqlite3,hashlib,shutil,sys,subprocess,zipfile
repo=Path('/home/ali/Documents/Codex/2026-10-02/task-4/rob2-kit');sys.path.insert(0,str(repo/'src'))
from rob2_kit.application.evidence import _evidence_catalog,source_reading_status,main_report_reading_status,_verified_source_projections
from rob2_kit.application.finalization import verify_bundle
root=repo.parent/'diagnostics/frozen-allsop-full-544a523';out=repo/'docs/evaluation/2026-10-03-allsop-completion-544a523';out.mkdir(exist_ok=True)
run=json.loads((root/'run.json').read_text());manifest=json.loads((root/'manifest.json').read_text())
assert manifest['guards']['input_tokens'] is None and manifest['guards']['uncached_input_tokens'] is None and run['input_limits_enabled'] is False
assert run['stop_reason'] is None and run['code_sha']=='544a523aa3b0ccec7459a5be32e3c87f5a95fb1a'
for name in ['manifest.json','prompt.txt','instructions.md','events.jsonl','run.json','response.txt','durable-token-usage-records.json','guard-offline-tests.json']:shutil.copyfile(root/name,out/name)
shutil.copyfile(root/'home/config.toml',out/'cli-config.toml')
for name in ['prepare-allsop-full-544a523.py','run_full_case_544a523.py','domain_probe_controls_telemetry.py','analyze-allsop-full-544a523.py']:shutil.copyfile(repo.parent/'diagnostics'/name,out/name)
pre=json.loads((root/'source-budget-preflight.json').read_text());pre.update(uncached_preflight_basis='Input counts are telemetry only; no total or uncached input cutoff. Source projection byte count is inherited from the identical verified sources, not a model usage guarantee.',prompt_utf8_bytes=len((root/'prompt.txt').read_bytes()),guards=manifest['guards'],qualification='Same verified source projection bytes as prior run; current prompt bytes and input telemetry-only guards. Transport/source bounds unchanged.')
(out/'source-budget-preflight.json').write_text(json.dumps(pre,indent=2)+'\n')
events=[json.loads(l) for l in (root/'events.jsonl').read_text().splitlines()];actions=[{'event_ordinal':n,**e['item']} for n,e in enumerate(events) if e['type']=='item.completed' and e.get('item',{}).get('type')=='mcp_tool_call'];saves=[i for i in actions if i['tool']=='save_domain_judgment']
with sqlite3.connect(f'file:{root}/workspace/.rob2-kit/canonical.sqlite3?mode=ro',uri=True) as c:state=json.loads(c.execute('select payload from workflow_head').fetchone()[0])
for name,value in [('submissions',saves),('accepted-domain-records',state['domain_records']),('selected-evidence',_evidence_catalog(root/'workspace','allsop-2014')),('domain-history-records',state['domain_history_records']),('reviews-and-closures',{'reviews':state['trial_reviews'],'closures':state['trial_closures']})]:
 (out/(name+'.json')).write_text(json.dumps(value,indent=2)+'\n')
with sqlite3.connect(f'file:{root}/workspace/.rob2-kit/derivative.sqlite3?mode=ro',uri=True) as c:reads=[dict(zip(['source_id','page','start_line','end_line'],r)) for r in c.execute('select source_id,page,start_line,end_line from page_reads order by source_id,page,start_line')]
contexts=[]
for i in actions:
 if i['tool']=='get_domain_context':
  result=(i.get('result')or{}).get('structured_content',{});data=result.get('data',{});contexts.append({'event_ordinal':i['event_ordinal'],'arguments':i['arguments'],'outcome':result.get('outcome'),'head':result.get('head'),'context_page':data.get('context_page'),'inline_primary_items':len(data.get('primary_report',[])),'coverage':data.get('coverage'),'reading_recovery':data.get('reading_recovery'),'first_question_ids':[q['id'] for q in data.get('questions',[])]})
assert all(x['inline_primary_items']==0 for x in contexts)
verified = _verified_source_projections(root/'workspace', {('allsop-2014',r['source_id']) for r in reads})
verified_status={}
for (_,source_id),(_,pages) in verified.items():
 complete=True
 for page,text in enumerate(pages,1):
  windows=sorted((r['start_line'],r['end_line']) for r in reads if r['source_id']==source_id and r['page']==page); next_line=1
  for start,end in windows:
   if start>next_line:break
   next_line=max(next_line,end+1)
  complete=complete and (next_line>len(text.splitlines()) if text.splitlines() else (0,0) in windows)
 verified_status[source_id]='read_complete' if complete else 'partially_read'
assert len(verified_status)==2 and set(verified_status.values())=={'read_complete'}
coverage={'read_windows':reads,'contexts':contexts,'verified_source_read_status':verified_status,'terminal_phase_source_reading_status':source_reading_status(root/'workspace','allsop-2014'),'terminal_phase_note':'Production helper scopes receipts to current phase and therefore returns empty after finalization. Archived assessment receipts were independently merged against verified complete projections above.','main_report_status':main_report_reading_status(root/'workspace',state['batch']['trials'],phase='assessment')['allsop-2014'],'qualification':'Actual response/delivery receipts and source-hash/projection verification, not comprehension.'};(out/'coverage.json').write_text(json.dumps(coverage,indent=2)+'\n')
bundle=root/'workspace'/state['artifact']['path'];shutil.copyfile(bundle,out/bundle.name)
with zipfile.ZipFile(bundle) as z:canonical=json.loads(z.read('canonical.json'))
diagnostic={};installed=verify_bundle(bundle,diagnostic=diagnostic)
independent=subprocess.run([sys.executable,str(repo/'scripts/verify_bundle.py'),str(bundle)],capture_output=True,text=True)
check={'phase':state['phase'],'artifact':state['artifact'],'installed_verifier':{'passed':installed,'diagnostic':diagnostic},'independent_verifier':{'passed':independent.returncode==0,'exit_code':independent.returncode,'stdout':independent.stdout,'stderr':independent.stderr},'scientific_pack_descriptor':canonical['scientific_pack'],'complete_workflow':state['phase']=='finalized','both_verifiers_pass':installed and independent.returncode==0,'qualification':'Finalization is model-owned and installed verifier passes. Standalone verifier rejects its scientific pack descriptor; do not call this independently verified.'};(out/'bundle-check.json').write_text(json.dumps(check,indent=2)+'\n')
shutil.copyfile(repo/'scripts/verify_bundle.py',out/'frozen-independent-verifier.py')
prev=repo/'docs/evaluation/2026-10-03-allsop-completion-b54db92/provisional-reference.json';shutil.copyfile(prev,out/prev.name)
orig=Path('/home/ali/Documents/Code/rob2-kit-benchmark/benchmark-luna6-medium-2026-10-01/cases/allsop-2014/.rob2-kit');assert all(hashlib.sha256((orig/n).read_bytes()).hexdigest()==h for n,h in manifest['source_database_sha256'].items())
usage=json.loads((root/'durable-token-usage-records.json').read_text());assert run['usage']['input_tokens']==sum(u['usage']['input_tokens'] for u in usage)
summary={'code_sha':run['code_sha'],'model':'gpt-6-luna','reasoning_effort':'medium','terminal':'finalized model-owned workflow','elapsed_seconds':run['elapsed_seconds'],'judgments':{v['domain_id']:v['judgment'] for v in state['domain_records'].values()},'usage':run['usage'],'uncached_input_tokens':run['uncached_input_tokens'],'input_limits_enabled':False,'mcp_calls':run['mcp_calls'],'save_calls':run['save_calls'],'save_rejections':run['rejections'],'per_domain':run['per_domain'],'guard_stop_reason':run['stop_reason'],'overshoots':{k:run[k] for k in ['output_overshoot','tool_start_overshoot','save_start_overshoot']},'source_database_hashes_unchanged':True,'known_case_mechanism_check':True,'paid_invocations':1,'operator_answer_repairs':0,'installed_verifier_passed':installed,'independent_verifier_passed':independent.returncode==0};(out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2));print('coverage',coverage['verified_source_read_status'])
