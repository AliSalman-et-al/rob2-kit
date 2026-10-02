import json,os,subprocess,time,selectors,signal,datetime,hashlib
from pathlib import Path
root=Path('diagnostics/production-d3-monarch-plus').resolve();manifest=json.loads((root/'manifest.json').read_text());env=os.environ.copy();env['CODEX_HOME']=str(root/'home');started=datetime.datetime.now(datetime.timezone.utc).isoformat();start=last=time.monotonic();usage={};calls=0;reason=None
cmd=['codex','exec','--strict-config','--ignore-rules','--skip-git-repo-check','-s','read-only','--ephemeral','-m','gpt-6-luna','-c','model_reasoning_effort="medium"','--json','-o',str(root/'response.txt'),'-']
with (root/'stderr.log').open('wb') as err,(root/'events.jsonl').open('wb') as log:
 proc=subprocess.Popen(cmd,cwd=root/'workspace',env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=err,start_new_session=True);proc.stdin.write((root/'prompt.txt').read_bytes());proc.stdin.close();sel=selectors.DefaultSelector();sel.register(proc.stdout,selectors.EVENT_READ);print('LAUNCHED',proc.pid,flush=True)
 while proc.poll() is None:
  for key,_ in sel.select(1):
   line=key.fileobj.readline()
   if not line:continue
   log.write(line);log.flush()
   try:e=json.loads(line)
   except:continue
   typ=e.get('type','');item=e.get('item',{});it=item.get('type','');last=time.monotonic()
   if typ=='turn.completed':usage=e.get('usage',{})
   if typ=='item.started' and it=='mcp_tool_call':calls+=1
   if it=='command_execution':reason='unapproved shell access'
   if calls>18:reason='tool-call guard'
   if usage.get('input_tokens',0)>400000 or usage.get('input_tokens',0)-usage.get('cached_input_tokens',0)>100000 or usage.get('output_tokens',0)>10000:reason='usage stop threshold'
   result=(item.get('result') or {}).get('structured_content',{});outcome=result.get('outcome') if isinstance(result,dict) else None
   print(typ,it,item.get('tool',''),outcome,'calls',calls,usage if typ=='turn.completed' else '',flush=True)
  if time.monotonic()-start>480:reason='wall stop'
  if time.monotonic()-last>120:reason='idle stop'
  if reason and proc.poll() is None:
   os.killpg(proc.pid,signal.SIGTERM)
   try:proc.wait(timeout=5)
   except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait()
 for line in proc.stdout:
  log.write(line)
  try:
   e=json.loads(line)
   if e.get('type')=='turn.completed':usage=e.get('usage',{})
  except:pass
response=root/'response.txt';r={'command':cmd,'started_at_utc':started,'completed_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'elapsed_seconds':round(time.monotonic()-start,2),'exit_code':proc.returncode,'stop_reason':reason,'tool_calls_started':calls,'usage':usage,'response_sha256':hashlib.sha256(response.read_bytes()).hexdigest() if response.exists() else None,'prediction_frozen_before_review':True};(root/'run.json').write_text(json.dumps(r,indent=2)+'\n');print('FROZEN',r,flush=True)
