"""Exactly one bounded fresh native D3 assessment. Never retry/resume."""
from pathlib import Path
import hashlib,json,os,selectors,signal,subprocess,time,tomllib
from diagnostic_evidence_preflight import launch_checked
R=Path(__file__).resolve().parent

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(n,x):(R/n).write_text(json.dumps(x,indent=2)+'\n')
def main():
 m=json.loads((R/'manifest.json').read_text());s=json.loads((R/'setup.json').read_text());home=Path(m['home']);work=Path(s['workspace'])
 cfg=tomllib.loads((home/'config.toml').read_text());assert (cfg['model'],cfg['model_reasoning_effort'])==('gpt-6-luna','medium')
 assert sha(R/'source-provenance.json')==m['source_provenance_sha256']
 assert sha(work/'.rob2-kit/canonical.sqlite3')==m['initial_canonical_sha256']
 assert not (R/'run.json').exists(),'No repeat authorized'
 for n,k in [('prompt.txt','prompt_sha256'),('private-criteria.md','private_criteria_sha256'),('run_once.py','runner_sha256')]:assert sha(R/n)==m[k]
 assert sha(home/'config.toml')==m['config_sha256'] and sha(Path(s['skill']))==m['skill_sha256']
 assert sha(R/'native-instructions.md')==m['instruction_sha256']
 protected_files={**json.loads((R/'protected-staging.json').read_text()),}
 def protected():
  for p,h in protected_files.items():assert sha(Path(p))==h,(p,'Scientific file changed')
  
 protected();assert not list((home/'sessions').rglob('*.jsonl'))
 baseline=set();records={};contexts=[];calls={};finals=set();rejected=[];consecutive_rejections=0;accepted=None;last_error=None;identical_errors=0;alerts=[];stop=None;buffer=b'';started=last=time.monotonic()
 command=['codex','exec','--strict-config','--ignore-rules','--skip-git-repo-check','-s','read-only','-m','gpt-6-luna',*m['flags'],'--json','-o',str(R/'response.txt'),'-'];write('command.json',command)
 def telemetry():
  nonlocal stop
  files=[p for p in (home/'sessions').rglob('*.jsonl') if str(p) not in baseline]
  if len(files)>1:stop=stop or 'multiple sessions'
  for p in files:
   for line in p.read_text().splitlines():
    try:row=json.loads(line)
    except ValueError:continue
    payload=row.get('payload',{})
    if row.get('type')=='token_usage_record':records[payload['response_id']]={'timestamp':row.get('timestamp'),**payload}
    if row.get('type')=='turn_context':
     ctx={'model':payload.get('model'),'effort':payload.get('effort')}
     if ctx not in contexts:contexts.append(ctx)
     if ctx!={'model':'gpt-6-luna','effort':'medium'}:stop=stop or 'model mismatch'
 def usage():return {k:sum(x['usage'].get(k,0) for x in records.values()) for k in ['input_tokens','cached_input_tokens','output_tokens','reasoning_output_tokens']}
 def consume(chunk):
  nonlocal buffer,last,stop,consecutive_rejections,accepted,last_error,identical_errors
  log.write(chunk);log.flush();buffer+=chunk
  while b'\n' in buffer:
   line,buffer=buffer.split(b'\n',1)
   if not line.strip():continue
   row=json.loads(line);item=row.get('item',{});kind=item.get('type')
   if kind=='mcp_tool_call' or (kind in {'agent_message','reasoning'} and any(item.get(k) for k in ['text','summary','content'])):last=time.monotonic()
   if kind=='mcp_tool_call':
    calls[item['id']]={'server':item.get('server'),'tool':item.get('tool'),'completed':row.get('type')=='item.completed'}
    if item.get('server')!='rob2' or item.get('tool') not in m['allowed_tools']:stop=stop or 'tool outside D3 allowlist'
   if kind=='mcp_tool_call' and item.get('tool')=='save_domain_judgment':
    if item.get('arguments',{}).get('domain_id') not in {None,'domain:missing'}:stop=stop or 'outside approved D3 scope'
    if item.get('arguments',{}).get('trial_id') not in {None,'award-1-2014'}:stop=stop or 'outside approved Trial scope'
    if row.get('type')=='item.completed':
     result=(item.get('result') or {}).get('structured_content') or {}
     if result.get('outcome')=='success':
      accepted=result;consecutive_rejections=0;stop=stop or 'accepted D3 checkpoint'
     else:
      consecutive_rejections+=1;rejected.append({'item':item,'consecutive':consecutive_rejections})
      fingerprint=json.dumps({'tool':item.get('tool'),'arguments':item.get('arguments'),'failure':result.get('condition',result.get('repairs',result.get('error')))},sort_keys=True)
      identical_errors=identical_errors+1 if fingerprint==last_error else 1;last_error=fingerprint
      if identical_errors>=3:stop=stop or 'three identical rejected submissions without repair'
   elif kind in {'command_execution','web_search','image_view','collab_tool_call'}:stop=stop or 'forbidden tool'
   if row.get('type')=='item.completed' and kind=='agent_message':finals.add(item['id'])
 def check():
  nonlocal stop
  telemetry();now=time.monotonic();u=usage()
  if (R/'stop-request.json').exists():stop=stop or json.loads((R/'stop-request.json').read_text())['reason']
  if not accepted and ((u['output_tokens']>=6000 and not any(a['reason']=='output review' for a in alerts)) or (now-started>=480 and not any(a['reason']=='wall review' for a in alerts)) or (now-last>=90 and not any(a['reason']=='idle review' for a in alerts))):
   reason='idle review' if now-last>=90 else 'wall review' if now-started>=480 else 'output review'
   alert={'reason':reason,'elapsed_seconds':now-started,'idle_seconds':now-last,'tool_calls':len(calls),'usage':u,'latest_tools':list(calls.values())[-3:]}
   alerts.append(alert);write('review-alerts.json',alerts);print(json.dumps({'review_alert':alert}),flush=True)
  write('live-progress.json',{'elapsed_seconds':now-started,'idle_seconds':now-last,'tool_calls':len(calls),'usage':u,'latest_tools':list(calls.values())[-3:],'review_alerts':alerts})
  return stop
 write('run.json',{'state':'started','no_retry':True,'command':command})
 assert m['limits']=={'invocations':1,'tool_count_stop':False,'input_token_stop':False,'output_review_threshold':6000,'wall_review_seconds':480,'idle_review_seconds':90,'identical_rejected_submissions_stop':3,'supervised':True}
 with (R/'events.jsonl').open('wb') as log,(R/'stderr.log').open('wb') as err:
  process=launch_checked(command,manifest_path=R/'availability-manifest.json',input_path=R/'availability-packet.bin',receipt_path=R/'launch-preflight.json',expected_manifest_sha256=m['availability_manifest_sha256'],cwd=work,env={**os.environ,'CODEX_HOME':str(home)},stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=err,start_new_session=True)
  process.stdin.write((R/'prompt.txt').read_bytes());process.stdin.close();os.set_blocking(process.stdout.fileno(),False);sel=selectors.DefaultSelector();sel.register(process.stdout,selectors.EVENT_READ)
  try:
   while process.poll() is None:
    for key,_ in sel.select(.25):
     chunk=os.read(key.fileobj.fileno(),65536)
     if chunk:consume(chunk)
    if check():break
  finally:
   if process.poll() is None:
    os.killpg(process.pid,signal.SIGTERM)
    try:process.wait(timeout=5)
    except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait()
   while True:
    try:chunk=os.read(process.stdout.fileno(),65536)
    except BlockingIOError:break
    if not chunk:break
    consume(chunk)
   sel.close();telemetry()
 protected();u=usage();write('durable-token-usage-records.json',list(records.values()));write('effective-model.json',contexts)
 write('run.json',{'exit_code':process.returncode,'stop':stop,'elapsed_seconds':time.monotonic()-started,'tool_calls':len(calls),'calls':calls,'agent_messages':len(finals),'provider_response_count':len(records),'usage':u,'uncached_input_tokens':u['input_tokens']-u['cached_input_tokens'],'model_context':contexts,'review_alerts':alerts,'accepted_checkpoint':accepted,'submission_rejections':rejected,'consecutive_submission_rejections':consecutive_rejections,'guards':'No tool-count/input-token stop. Output/wall/idle thresholds are supervised review alerts. Only accepted D3, forbidden tool/scope/model, or three identical rejected submissions stop automatically; one exec, no retries','retry_or_continuation':False,'scientific_original_and_staging_hashes_unchanged':True})
 write('answer-freeze.json',{n:sha(R/n) for n in ['response.txt','events.jsonl','run.json','durable-token-usage-records.json'] if (R/n).exists()});print(json.dumps({'terminal_stop':stop,'elapsed_seconds':time.monotonic()-started,'tool_calls':len(calls),'usage':u,'accepted':accepted is not None,'rejections':len(rejected)}));print('Output frozen before adjudication; answers not printed.')
if __name__=='__main__':main()
