from pathlib import Path
import sys,os,json,hashlib,tomllib,selectors,subprocess,time,signal
root=Path(sys.argv[1]).resolve();manifest=json.loads((root/'manifest.json').read_text());prompt=(root/'prompt.txt').read_text();conf=tomllib.loads((root/'home/config.toml').read_text())
assert manifest['model']=='gpt-6-luna' and conf['model']=='gpt-6-luna' and conf['model_reasoning_effort']=='medium'
assert 'mcp_servers' not in conf and not (root/'run.json').exists() and not list((root/'home/sessions').rglob('*.jsonl'))
assert hashlib.sha256(prompt.encode()).hexdigest()==manifest['prompt_sha256'] and manifest['preflight_input_token_upper_bound']<20000
command=['codex','exec','--strict-config','--ignore-rules','--skip-git-repo-check','-s','read-only','-m','gpt-6-luna','-c','model_reasoning_effort="medium"','-c','features.code_mode={enabled=false}','--disable','shell_tool','--disable','unified_exec','--json','-o',str(root/'response.txt'),'-']
env={**os.environ,'CODEX_HOME':str(root/'home')};start=last=time.monotonic();usage={};records={};reason=None;tools=0;finals=0

def record_usage():
 global usage,records
 paths=list((root/'home/sessions').rglob('*.jsonl'));assert len(paths)<=1
 if paths:
  for line in paths[0].read_text().splitlines():
   try:r=json.loads(line)
   except ValueError:continue
   if r.get('type')=='token_usage_record':q=r['payload'];records[q['response_id']]={'timestamp':r.get('timestamp'),**q}
  usage={k:sum(r['usage'].get(k,0) for r in records.values()) for k in ['input_tokens','cached_input_tokens','output_tokens','reasoning_output_tokens']}
  (root/'durable-token-usage-records.json').write_text(json.dumps(list(records.values()),indent=2)+'\n')

def consume(raw):
 global last,reason,tools,finals
 log.write(raw);log.flush();last=time.monotonic();r=json.loads(raw);i=r.get('item',{})
 if i.get('type') in ['mcp_tool_call','command_execution','tool_call'] and r.get('type')=='item.started':tools+=1;reason=reason or 'unexpected tool call'
 if r.get('type') in ['error','turn.failed']:reason=reason or 'CLI error: '+str(r.get('message',r.get('error','unspecified')))
 if i.get('type')=='agent_message' and r.get('type')=='item.completed':finals+=1
with (root/'events.jsonl').open('wb') as log,(root/'stderr.log').open('wb') as err:
 proc=subprocess.Popen(command,cwd=root/'workspace',env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=err,start_new_session=True)
 proc.stdin.write(prompt.encode());proc.stdin.close();sel=selectors.DefaultSelector();sel.register(proc.stdout,selectors.EVENT_READ)
 try:
  while proc.poll() is None:
   for key,_ in sel.select(1):
    raw=proc.stdout.readline()
    if raw:consume(raw)
   record_usage()
   if time.monotonic()-start>=480:reason=reason or 'wall threshold'
   if time.monotonic()-last>=120:reason=reason or 'idle threshold'
   if usage.get('input_tokens',0)>=20000:reason=reason or 'input threshold'
   if usage.get('output_tokens',0)>=2500:reason=reason or 'output threshold'
   if len(records)>1:reason=reason or 'unexpected second response generation'
   if reason:break
 finally:
  if proc.poll() is None:
   os.killpg(proc.pid,signal.SIGTERM)
   try:proc.wait(timeout=5)
   except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait()
  for raw in proc.stdout:consume(raw)
  record_usage();sel.close()
response=(root/'response.txt').read_text() if (root/'response.txt').exists() else ''
result={'manifest':manifest,'command':command,'elapsed_seconds':time.monotonic()-start,'stop_reason':reason or 'completed one response','exit_code':proc.returncode,'tool_calls':tools,'final_messages':finals,'durable_response_generations':len(records),'usage':usage,'uncached_input_tokens':usage.get('input_tokens',0)-usage.get('cached_input_tokens',0),'response_word_count':len(response.split()),'response':response,'no_retry':True,'input_overshoot':max(0,usage.get('input_tokens',0)-20000),'output_overshoot':max(0,usage.get('output_tokens',0)-2500)}
(root/'run.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
