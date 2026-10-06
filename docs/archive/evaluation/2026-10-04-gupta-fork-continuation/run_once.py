"""One authorized fork experiment; cumulative guards across at most two turns."""
from __future__ import annotations
import hashlib,json,os,selectors,signal,subprocess,time
from pathlib import Path
from diagnostic_evidence_preflight import launch_checked
from rob2_kit.application.status import get_status
R=Path(__file__).parent;ROOT=R.resolve().parents[2];m=json.loads((R/'run-manifest.json').read_text());D=Path(m['staging']);HOME=Path(m['home']);PY='/home/ali/Documents/Codex/2026-10-02/task/rob2-kit/.venv/bin/python'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(name,obj):(R/name).write_text(json.dumps(obj,indent=2)+'\n')
assert not (R/'experiment.json').exists(),'No restart or retry'
assert sha(R/'prompt.txt')==m['prompt_sha256'];assert sha(D/'availability-packet.txt')==m['availability_packet_sha256'];assert sha(Path(__file__))==m['runner_sha256']
assert (m['model'],m['effort'])==('gpt-6-luna','medium');assert m['limits']=={'turns':2,'wall_seconds':600,'tools':35,'output_tokens':8000,'idle_seconds':120,'no_progress_boundaries':2,'identical_errors':2,'input_telemetry_only':True}
original=json.loads((R/'original-preservation.json').read_text());assert all(sha(Path(p))==h for p,h in original.items())
fork_file=next(p for p in (HOME/'sessions').rglob('*.jsonl') if m['fork_id'] in p.name);assert sha(fork_file)==m['baseline_fork_sha256']
baseline=set(m['baseline_response_ids']);records={};calls=set();contexts=[];turns=[];stop=None;previous_error=None;identical=0;no_progress=0;started=last=time.monotonic();buffer=b''
# Diagnostic adapter only; application status is flat, MCP status is enveloped.
def status():
 flat=get_status(D/'workspace')
 return {'head':{'phase':flat['phase'],'state_revision':flat['state_revision'],'next_action':flat.get('continuation') or {}},'data':flat}
initial=status();assert initial['head']['state_revision']==8
# Recorded existing approvals are not changed by controller.
def telemetry():
 global stop
 for line in fork_file.read_text().splitlines():
  try:r=json.loads(line)
  except ValueError:continue
  p=r.get('payload') or {}
  if r['type']=='token_usage_record' and p['response_id'] not in baseline:records[p['response_id']]={'timestamp':r.get('timestamp'),**p}
  if r['type']=='turn_context':
   if p.get('turn_id') in ['01a10362-9833-7811-8d40-e68dbfaff347','01a10365-9be4-7110-bde3-69ace622b9b1']:continue
   x={'turn_id':p.get('turn_id'),'model':p.get('model'),'effort':p.get('effort'),'cwd':p.get('cwd')}
   if x not in contexts:contexts.append(x)
   if x['model']!='gpt-6-luna' or x['effort']!='medium' or x['cwd']!=str(D/'workspace'):stop=stop or 'effective model/effort/workspace mismatch'
def usage():return {k:sum(r['usage'].get(k,0) for r in records.values()) for k in ['input_tokens','cached_input_tokens','output_tokens','reasoning_output_tokens']}
def save():
 write('experiment.json',{'stop':stop,'turns':turns,'calls':len(calls),'elapsed_seconds':time.monotonic()-started,'usage':usage(),'input_telemetry_only':True,'no_retry':True,'fork_id':m['fork_id']})
def envelope(item):
 result=item.get('result') or {};payload=result.get('structured_content')
 if not isinstance(payload,dict):
  for c in result.get('content',[]):
   if c.get('type')=='text':
    try:x=json.loads(c.get('text',''))
    except ValueError:continue
    if isinstance(x,dict) and 'outcome' in x:payload=x;break
 return payload if isinstance(payload,dict) else {}
def consume(chunk,n,log):
 global buffer,last,stop,identical,previous_error
 log.write(chunk);log.flush();buffer+=chunk
 while b'\n' in buffer:
  line,buffer=buffer.split(b'\n',1)
  if not line.strip():continue
  row=json.loads(line);last=time.monotonic();i=row.get('item') or {}
  if row.get('type')=='thread.started' and row.get('thread_id')!=m['fork_id']:stop=stop or 'session changed'
  if i.get('type') in ['command_execution','web_search','collab_tool_call','image_view']:stop=stop or 'unexpected non-MCP tool'
  if i.get('type')=='mcp_tool_call' and row['type'] in ['item.started','item.completed']:
   calls.add((n,i['id']))
   if row['type']=='item.completed':
    p=envelope(i);action=(p.get('head') or {}).get('next_action') or {}
    if action.get('authority')=='researcher' or p.get('outcome')=='review_required':stop=stop or 'new researcher gate'
    error=i.get('error') or (p.get('outcome') in ['error','repair','condition']) or (not p.get('outcome'))
    if error:
     semantic=json.dumps({'tool':i.get('tool'),'error':i.get('error'),'payload':{k:v for k,v in p.items() if k not in ['head','counters']}},sort_keys=True)
     identical=identical+1 if semantic==previous_error else 1;previous_error=semantic
    else:identical=0;previous_error=None
  telemetry()
def check():
 global stop
 telemetry();elapsed=time.monotonic()-started;idle=time.monotonic()-last
 for hit,reason in [(elapsed>=600,'cumulative wall limit'),(idle>=120,'idle limit'),(len(calls)>=35,'cumulative tool limit'),(usage()['output_tokens']>=8000,'cumulative output limit'),(identical>=2,'repeated identical error'),(no_progress>=2,'two no-progress boundaries')]:
  if hit:stop=stop or reason
 return stop
save()
for n in [1,2]:
 if check():break
 before=status();last=time.monotonic();prompt=(R/'prompt.txt').read_text()
 command=['codex','exec','resume','--strict-config','--ignore-rules','--skip-git-repo-check','-m','gpt-6-luna',*m['cli_config_flags'],'--json','-o',str(R/f'response-{n}.txt'),m['fork_id'],'-']
 write(f'command-{n}.json',command);turns.append({'index':n,'state':'started','command':command});save();buffer=b''
 with (R/f'turn-{n}.jsonl').open('wb') as log,(D/f'stderr-{n}.log').open('wb') as err:
  p=launch_checked(command,manifest_path=R/'availability-manifest.json',input_path=D/'availability-packet.txt',receipt_path=R/f'launch-preflight-{n}.json',expected_manifest_sha256=m['availability_manifest_sha256'],cwd=D/'workspace',env={**os.environ,'CODEX_HOME':str(HOME)},stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=err,start_new_session=True)
  p.stdin.write(prompt.encode());p.stdin.close();os.set_blocking(p.stdout.fileno(),False);sel=selectors.DefaultSelector();sel.register(p.stdout,selectors.EVENT_READ)
  try:
   while p.poll() is None:
    for key,_ in sel.select(.25):
     chunk=os.read(key.fileobj.fileno(),65536)
     if chunk:consume(chunk,n,log)
    if check():break
  finally:
   if p.poll() is None:
    os.killpg(p.pid,signal.SIGTERM)
    try:p.wait(timeout=5)
    except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait()
   while True:
    try:chunk=os.read(p.stdout.fileno(),65536)
    except BlockingIOError:break
    if not chunk:break
    consume(chunk,n,log)
   sel.close();telemetry()
 after=status();turns[-1].update({'state':'ended','exit_code':p.returncode,'before_revision':before['head']['state_revision'],'after_revision':after['head']['state_revision'],'phase':after['head']['phase']})
 progress=before['head']!=after['head'] or before['data'].get('main_report_reading')!=after['data'].get('main_report_reading')
 no_progress=0 if progress else no_progress+1;write(f'status-after-{n}.json',after);check();save()
 if stop or after['head']['phase']=='finalized':break
 if p.returncode!=0:stop='nonzero model process exit';save();break
 if after['head']['next_action'].get('authority')=='researcher':stop='new researcher gate';save();break
telemetry();save();write('durable-token-usage-records.json',list(records.values()));write('effective-model.json',contexts);write('final-status.json',status())
write('output-freeze.json',{p.name:sha(p) for p in sorted(R.iterdir()) if p.is_file() and (p.name.startswith(('response-','turn-','status-after-')) or p.name in ['experiment.json','durable-token-usage-records.json','effective-model.json','final-status.json'])})
assert all(sha(Path(p))==h for p,h in original.items()),'Original artifacts changed'
print(json.dumps({'turns':len(turns),'tools':len(calls),'usage':usage(),'stop':stop,'originals_unchanged':True,'outputs_frozen':True},indent=2))
