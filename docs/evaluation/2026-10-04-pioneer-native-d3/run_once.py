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
 protected_files={**json.loads((R/'protected-staging.json').read_text()),}
 def protected():
  for p,h in protected_files.items():assert sha(Path(p))==h,(p,'Scientific file changed')
  
 protected();assert not list((home/'sessions').rglob('*.jsonl'))
 baseline=set();records={};contexts=[];calls={};finals=set();rejected=[];consecutive_rejections=0;accepted=None;stop=None;buffer=b'';started=last=time.monotonic()
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
  nonlocal buffer,last,stop,consecutive_rejections,accepted
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
    if item.get('arguments',{}).get('domain_id')!='domain:missing':stop=stop or 'outside approved D3 scope'
    if row.get('type')=='item.completed':
     result=(item.get('result') or {}).get('structured_content') or {}
     if result.get('outcome')=='success':
      accepted=result;consecutive_rejections=0;stop=stop or 'accepted D3 checkpoint'
     else:
      consecutive_rejections+=1;rejected.append({'item':item,'consecutive':consecutive_rejections})
      if consecutive_rejections>=2:stop=stop or 'two consecutive submission rejections'
   elif kind in {'command_execution','web_search','image_view','collab_tool_call'}:stop=stop or 'forbidden tool'
   if row.get('type')=='item.completed' and kind=='agent_message':finals.add(item['id'])
 def check():
  nonlocal stop
  telemetry();now=time.monotonic();u=usage()
  if len(calls)>30:stop=stop or 'tool limit exceeded'
  elif len(calls)==30 and all(c['completed'] for c in calls.values()) and not accepted:stop=stop or 'tool limit reached'
  elif u['output_tokens']>=6000:stop=stop or 'output limit'
  elif now-started>=480:stop=stop or 'wall limit'
  elif now-last>=90:stop=stop or 'genuine idle limit'
  return stop
 write('run.json',{'state':'started','no_retry':True,'command':command})
 assert m['limits']=={'invocations':1,'tools':30,'output_tokens':6000,'wall_seconds':480,'genuine_idle_seconds':90,'consecutive_submission_rejections':2,'input_telemetry_only':True}
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
 write('run.json',{'exit_code':process.returncode,'stop':stop,'elapsed_seconds':time.monotonic()-started,'tool_calls':len(calls),'calls':calls,'agent_messages':len(finals),'provider_response_count':len(records),'usage':u,'uncached_input_tokens':u['input_tokens']-u['cached_input_tokens'],'model_context':contexts,'output_overshoot':max(0,u['output_tokens']-6000),'accepted_checkpoint':accepted,'submission_rejections':rejected,'consecutive_submission_rejections':consecutive_rejections,'tool_overshoot':max(0,len(calls)-30),'wall_overshoot_seconds':max(0,time.monotonic()-started-480),'guards':'Reactive output/time/tool telemetry, not provider-enforced token cap; exactly one exec, no retries','retry_or_continuation':False,'scientific_original_and_staging_hashes_unchanged':True})
 write('answer-freeze.json',{n:sha(R/n) for n in ['response.txt','events.jsonl','run.json','durable-token-usage-records.json'] if (R/n).exists()});print((R/'run.json').read_text());print('Output frozen before adjudication.')
if __name__=='__main__':main()
