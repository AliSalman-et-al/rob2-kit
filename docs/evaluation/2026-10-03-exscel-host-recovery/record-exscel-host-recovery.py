from pathlib import Path
import json,sqlite3,sys,hashlib,shutil,subprocess
repo=Path.cwd();D=repo.parent/'diagnostics';root=D/'exscel-host-recovery';prior=D/'frozen-exscel-bd92ec8';w=prior/'workspace';code=D/'frozen-exscel-bd92ec8-code';sys.path.insert(0,str(code/'src'));from rob2_kit.application.finalization import verify_bundle
out=repo/'docs/evaluation/2026-10-03-exscel-host-recovery';out.mkdir(exist_ok=True)
for p in root.iterdir():
 if p.is_file():shutil.copyfile(p,out/p.name)
for n in ['run-exscel-host-recovery.py','exscel_recovery_monitor.py','test_exscel_recovery_monitor.py','domain_probe_controls_telemetry.py']:
 shutil.copyfile(D/n,out/n)
shutil.copyfile(Path(__file__),out/Path(__file__).name)
canon=w/'.rob2-kit/canonical.sqlite3';frozen=hashlib.sha256(canon.read_bytes()).hexdigest()
with sqlite3.connect(f'file:{canon}?mode=ro',uri=True) as c:state=json.loads(c.execute('select payload from workflow_head').fetchone()[0])
(out/'frozen-final-state.json').write_text(json.dumps(state,indent=2)+'\n')
with sqlite3.connect(f'file:{w}/.rob2-kit/derivative.sqlite3?mode=ro',uri=True) as c:
 c.row_factory=sqlite3.Row;reads=[dict(r) for r in c.execute('select * from page_reads')]
(out/'source-read-receipts.json').write_text(json.dumps(reads,indent=2)+'\n')
rollout=next((D/'frozen-exscel-full-bd92ec8/home/sessions').rglob('*.jsonl'));monitor=json.loads((root/'monitor.json').read_text());new_ids=set(monitor['new_response_ids']);usage_records=[];contexts=[]
for l in rollout.read_text().splitlines():
 row=json.loads(l);v=row.get('payload',{})
 if row['type']=='token_usage_record' and v['response_id'] in new_ids:usage_records.append(v)
 if row['type']=='turn_context':contexts.append({k:v.get(k) for k in ['model','effort','turn_id']})
assert contexts and all((v['model'],v['effort'])==('gpt-6-luna','medium') for v in contexts)
(out/'recovery-only-response-usage.json').write_text(json.dumps(usage_records,indent=2)+'\n');(out/'model-settings.json').write_text(json.dumps(contexts,indent=2)+'\n')
artifact=state.get('artifact');verification={'phase':state['phase'],'installed':None,'independent':None}
if state['phase']=='finalized' and isinstance(artifact,dict):
 bundle=w/artifact['path'];diag={};verification['installed']={'passed':verify_bundle(bundle,diag),'diagnostic':diag}
 check=subprocess.run(['/home/ali/Documents/Codex/2026-10-02/task/rob2-kit/.venv/bin/python',str(code/'scripts/verify_bundle.py'),str(bundle)],text=True,capture_output=True)
 verification['independent']={'passed':check.returncode==0,'exit_code':check.returncode,'stdout':check.stdout,'stderr':check.stderr};shutil.copyfile(bundle,out/bundle.name)
(out/'both-verifiers.json').write_text(json.dumps(verification,indent=2)+'\n')
assert hashlib.sha256(canon.read_bytes()).hexdigest()==frozen
completion=json.loads((root/'completion.json').read_text());u=monitor['usage'];old=json.loads((D/'frozen-exscel-full-bd92ec8/run.json').read_text())['usage'];proposal=json.loads((prior/'run.json').read_text())['usage'];sum_all={k:u.get(k,0)+old.get(k,0)+proposal.get(k,0) for k in ['input_tokens','cached_input_tokens','output_tokens','reasoning_output_tokens']}
summary={'boundary':completion['boundary'],'reason':completion['reason'],'phase':state['phase'],'revision':state['revision'],'domain_count':len(state.get('domain_records',{})),'resumed_turns':len(completion['turns']),'same_session':json.loads((root/'manifest.json').read_text())['session'],'host_assisted_recovery':True,'original_failed_run_remains_failure':True,'scientific_code':'bd92ec84fb1b24a05ac742db8ea01f3c9b7bcf6a','host_commit':json.loads((root/'manifest.json').read_text())['host_commit'],'monitor':monitor,'prior_failed_continuation_usage':old,'proposal_usage':proposal,'combined_EXSCEL_usage':sum_all,'combined_uncached_input_tokens':sum_all['input_tokens']-sum_all['cached_input_tokens'],'combined_input_plus_output':sum_all['input_tokens']+sum_all['output_tokens'],'both_verifiers':verification,'approval_repeated':False,'operator_repairs':0,'cost_dollars':None,'independent_scientific_audit':'pending after this freeze'}
(out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2))
