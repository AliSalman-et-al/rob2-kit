import os,json,time,subprocess,selectors,signal,hashlib,datetime
from pathlib import Path
root=Path('docs/evaluation/2026-10-02-d5-guidance-probe').resolve();m=json.loads((root/'manifest.json').read_text());results=[]
for case in m['cases']:
 p=Path(case['case_directory']);env=os.environ.copy();env['CODEX_HOME']=case['cli_home'];started=datetime.datetime.now(datetime.timezone.utc).isoformat();start=time.monotonic();last=start;events=[];reason=None;usage={}
 cmd=['codex','exec','--strict-config','--ignore-rules','--skip-git-repo-check','-s','read-only','-m','gpt-6-luna','-c','model_reasoning_effort="medium"','--json','-o',str(p/'response.txt'),'-']
 with (p/'stderr.log').open('wb') as err,(p/'events.jsonl').open('wb') as log:
  proc=subprocess.Popen(cmd,cwd=p,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=err,start_new_session=True)
  proc.stdin.write(Path(case['prompt_file']).read_bytes());proc.stdin.close();sel=selectors.DefaultSelector();sel.register(proc.stdout,selectors.EVENT_READ)
  print(case['case'],'LAUNCHED',proc.pid,flush=True)
  while proc.poll() is None:
   for key,_ in sel.select(1):
    line=key.fileobj.readline()
    if not line:continue
    log.write(line);log.flush()
    try:e=json.loads(line)
    except:continue
    events.append(e);typ=e.get('type','');last=time.monotonic()
    if typ=='turn.completed':usage=e.get('usage',{})
    item=e.get('item',{});it=item.get('type','')
    if it and it not in ['agent_message','reasoning']:reason='tool-free violation: '+it
    print(case['case'],typ,it,usage if typ=='turn.completed' else '',flush=True)
    inp=usage.get('input_tokens',0);cached=usage.get('cached_input_tokens',0)
    if inp>30000 or inp-cached>20000 or usage.get('output_tokens',0)>4000:reason='approved usage stop threshold reached'
   if time.monotonic()-start>480:reason='wall stop'
   if time.monotonic()-last>120:reason='idle stop'
   if reason and proc.poll() is None:
    os.killpg(proc.pid,signal.SIGTERM)
    try:proc.wait(timeout=5)
    except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait()
  # Drain completed process output without reviewing prediction contents.
  for line in proc.stdout:
   log.write(line)
   try:
    e=json.loads(line)
    if e.get('type')=='turn.completed':usage=e.get('usage',{})
   except:pass
 durable=[]
 for rollout in Path(case['cli_home']).joinpath('sessions').rglob('*.jsonl'):
  for raw in rollout.read_text().splitlines():
   row=json.loads(raw);payload=row.get('payload',{})
   if (row.get('type')=='event_msg' and payload.get('type')=='token_count') or row.get('type')=='session_meta':durable.append(row)
 (p/'durable-usage-events.json').write_text(json.dumps(durable,indent=2)+'\n')
 response=p/'response.txt';r={'case':case['case'],'command':cmd,'started_at_utc':started,'completed_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'elapsed_seconds':round(time.monotonic()-start,2),'exit_code':proc.returncode,'stop_reason':reason,'usage':usage,'response_sha256':hashlib.sha256(response.read_bytes()).hexdigest() if response.exists() else None};results.append(r);(p/'run.json').write_text(json.dumps(r,indent=2)+'\n');print(case['case'],'FROZEN',r,flush=True)
(root/'predictions-frozen.json').write_text(json.dumps({'both_predictions_frozen_before_review':True,'results':results},indent=2)+'\n')
