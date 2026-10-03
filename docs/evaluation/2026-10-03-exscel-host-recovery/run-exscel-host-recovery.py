from pathlib import Path
import json,sqlite3,sys,subprocess,os,hashlib,time,shutil
D=Path(__file__).resolve().parent;repo=D.parent/'rob2-kit';sys.path[:0]=[str(repo/'scripts'),str(D),str(D/'frozen-exscel-bd92ec8-code/src')]
from workflow_completion import drive,Turn
from exscel_recovery_monitor import Monitor
from rob2_kit.application.status import get_status
from rob2_kit.application.finalization import verify_bundle
code=D/'frozen-exscel-bd92ec8-code';prior=D/'frozen-exscel-full-bd92ec8';w=D/'frozen-exscel-bd92ec8/workspace';root=D/'exscel-host-recovery';root.mkdir();session='01a101e4-5479-72f1-baf2-bc69f7221a18'
assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=code,text=True).strip()=='bd92ec84fb1b24a05ac742db8ea01f3c9b7bcf6a';assert not subprocess.check_output(['git','status','--porcelain'],cwd=code)
rollouts=list((prior/'home/sessions').rglob('*.jsonl'));assert len(rollouts)==1 and session in rollouts[0].name
with sqlite3.connect(f'file:{w}/.rob2-kit/canonical.sqlite3?mode=ro',uri=True) as c:s=json.loads(c.execute('select payload from workflow_head').fetchone()[0])
assert s['phase']=='assessment' and s['revision']==4 and s['proposal_acknowledgment']['review_identity']=='sha256:c8091d311b549d5d26848195814279c93f2ce1e8ef2b9709bcf692c91c7a4a66'
(root/'initial-state.json').write_text(json.dumps(s,indent=2)+'\n');original_config=(prior/'home/config.toml').read_bytes()
controller=repo/'scripts/workflow_completion.py';shutil.copyfile(controller,root/'workflow_completion.py');(root/'source-session-baseline.json').write_text(json.dumps({'session':session,'rollout_path':str(rollouts[0]),'rollout_sha256_before':hashlib.sha256(rollouts[0].read_bytes()).hexdigest(),'old_run':json.loads((prior/'run.json').read_text()),'original_config_sha256':hashlib.sha256(original_config).hexdigest()},indent=2)+'\n')
manifest={'session':session,'scientific_code_sha':'bd92ec84fb1b24a05ac742db8ea01f3c9b7bcf6a','host_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip(),'controller_sha256':hashlib.sha256(controller.read_bytes()).hexdigest(),'model':'gpt-6-luna','effort':'medium','workspace':str(w),'authorization':'Explicit parent authorization: ONE recovery experiment on SAME approved EXSCEL session. Original failed run preserved. Up to3resumed turns/900secsharedwall/180secidle/60cumulativetools/12kcumulativeoutput/2consecutivenoprogress or identicalerrors;inputtelemetry;no fresh session,automaticapproval,operatorrepair,furtherexperiment.','limits':{'resumed_turns':3,'wall_seconds':900,'idle_seconds':180,'tools':60,'output_tokens':12000,'no_progress_boundaries':2,'input_tokens':None},'guard_scope':'ONE Monitor instance and baseline response-ID set shared across every turn; tool IDs namespaced by resumed turn; original usage excluded.'}
(root/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')

def status():
 r=get_status(w)
 with sqlite3.connect(f'file:{w}/.rob2-kit/derivative.sqlite3?mode=ro',uri=True) as c:
  # Durable delivery only: no timestamps, transient views or search-query novelty.
  contexts=[list(x) for x in c.execute('select trial_id,domain_id,state_revision,digest,page_size,max(next_index) from domain_context_views group by trial_id,domain_id,state_revision,digest,page_size order by trial_id,domain_id,state_revision,digest,page_size')]
  reads=[list(x) for x in c.execute('select source_id,page,start_line,end_line from page_reads where phase="assessment" and trial_id="exscel" order by source_id,page,start_line,end_line')]
 r['host_progress']={'delivered_context':contexts,'delivered_read_ranges':reads}
 return r

def verify(r):
 if r.get('phase')!='finalized':return False
 artifact=r.get('artifact')
 if not isinstance(artifact,dict):return False
 p=(w/artifact['path']).resolve();assert p.is_relative_to(w)
 return verify_bundle(p)

prompt='Resume this SAME approved assessment from authoritative get_status and the preserved working checkpoint. Complete the remaining Domains, inspect decisive Trial review findings, close with the exact returned Review identity, and finalize the Batch. Follow installed production guidance and all pending context/source-reading continuations; inspect complete relevant definitions and applicable captured plans when needed. Scientific judgments are yours, with material unknowns and counterevidence retained. Do not stop merely because a turn, context page or Domain ended. Stop for an actual researcher-authority action, unrecoverable blocker or the shared experiment guards. Do not request or record approval: existing scope approval remains valid. Preserve all source identity conflicts. No operator case hints, repairs or new session. This is explicitly host-assisted recovery, not one-turn success. Shared experiment guards across at most3resumed turns: wall900seconds/idle180seconds/60tools/12000outputtokens;inputtelemetry;two consecutive no-progress boundaries or identicalerrors.'
(root/'initial-prompt.txt').write_text(prompt)
monitor=Monitor(rollouts[0]);assert sum(x['usage']['input_tokens'] for x in monitor.baseline.values())==334932
(root/'guard-preflight.json').write_text(json.dumps({'same_session_verified':True,'baseline_excluded_input_tokens':334932,'original_config_unchanged':True,'no_prior_Domain_answers_added':True,'one_shared_monitor':True,'cross_turn_guard_tests':'passed offline baseline/cross-turn responseIDs and reused toolIDs/sharedwall/idle/repeatederrors'},indent=2)+'\n')

def invoke(sid,message,remaining,index):
 assert sid==session and index<3
 cmd=['codex','exec','resume',session,'--strict-config','--ignore-rules','--skip-git-repo-check','-m','gpt-6-luna','-c','model_reasoning_effort="medium"','-c','features.code_mode={enabled=true,direct_only_tool_namespaces=["mcp__rob2"]}','--json','-o',str(root/f'turn-{index}.response.txt'),'-']
 (root/f'turn-{index}.prompt.txt').write_text(message);(root/f'turn-{index}.command.json').write_text(json.dumps(cmd,indent=2)+'\n')
 trace=root/f'turn-{index}.events.jsonl'
 code=monitor.invoke(cmd,message,cwd=w,env={**os.environ,'CODEX_HOME':str(prior/'home')},trace=trace,stderr=root/f'turn-{index}.stderr.log')
 (root/f'turn-{index}.monitor.json').write_text(json.dumps(monitor.summary(),indent=2)+'\n')
 if not trace.exists():trace.write_text('')
 return Turn(code,trace)

result=drive(invoke,status,verify,prompt=prompt,session=session,max_resumes=2,no_progress_limit=2,wall_seconds=900)
assert (prior/'home/config.toml').read_bytes()==original_config
(root/'completion.json').write_text(json.dumps(result,indent=2)+'\n');(root/'monitor.json').write_text(json.dumps(monitor.summary(),indent=2)+'\n');(root/'final-status.json').write_text(json.dumps(status(),indent=2)+'\n')
print(json.dumps({'boundary':result['boundary'],'reason':result['reason'],'turns':len(result['turns']),**monitor.summary()},indent=2))
