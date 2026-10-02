import os,json,time,subprocess,selectors,signal,hashlib,datetime,sys
from pathlib import Path
case='deliver'
root=Path('../diagnostics/frozen-deliver-d3-db8e68d').resolve();out=root/'retained';out.mkdir()
assert not (root/'run.json').exists();m=json.loads((root/'manifest.json').read_text());assert subprocess.check_output(['git','rev-parse','HEAD']).decode().strip()==m['code_sha']
env=os.environ.copy();env['CODEX_HOME']=str(root/'home');start=last=time.monotonic();started=datetime.datetime.now(datetime.timezone.utc).isoformat();reason=None;calls=completed=saves=rejections=0;usage={};records={};sampled={};rollout=None;events=[];declaration=None;declaration_verified=False;code_calls=0
cmd=['codex','exec','--strict-config','--ignore-rules','--skip-git-repo-check','-s','read-only','-m','gpt-6-luna','-c','model_reasoning_effort="medium"','--json','-o',str(root/'response.txt'),'-']
def usage_read():
 global rollout,usage,declaration,declaration_verified,code_calls,reason
 if rollout is None:
  paths=list((root/'home/sessions').rglob('*.jsonl'))
  if paths:rollout=paths[0]
 if rollout:
  code_calls=0
  for line in rollout.read_text().splitlines():
   try:r=json.loads(line)
   except json.JSONDecodeError:continue
   if r.get('type')=='response_item':
    item=r.get('payload',{})
    if item.get('type')=='custom_tool_call':code_calls+=1
    if item.get('type')=='custom_tool_call_output':
     for block in item.get('output',[]):
      t=block.get('text','');n=t.find('declare const tools: { mcp__rob2__save_domain_judgment')
      if n>=0:
       declaration=t[n:].split('): Promise<',1)[0]
       declaration_verified='answers: Array<unknown>' not in declaration and all(x in declaration for x in ['answers:', 'bases', 'evidence: string', 'role:', 'question_id:', 'justification:', 'unknowns:', 'counterevidence:'])
       (root/'hosted-input-declaration.json').write_text(json.dumps({'actual_model_visible_declaration':declaration,'nested_answer_fields_verified':declaration_verified,'capture':'Saved custom_tool_call_output received by the model through functions.exec / ALL_TOOLS, not native schema reconstruction'},indent=2)+'\n')
       if not declaration_verified:reason=reason or 'hosted answer declaration still hides required fields'
  if code_calls>=16:reason=reason or '16 model code-tool calls'
  for line in rollout.read_text().splitlines():
   try:r=json.loads(line)
   except json.JSONDecodeError:continue
   if r.get('type')=='token_usage_record':
    p=r['payload'];records[p['response_id']]={'timestamp':r.get('timestamp'),'response_id':p['response_id'],'usage':p['usage'],'turn_token_usage':p['turn_token_usage']};usage=p['turn_token_usage']
  (root/'durable-token-usage-records.json').write_text(json.dumps(list(records.values()),indent=2)+'\n')
def event(raw):
 global last,usage,calls,completed,saves,rejections,reason
 try:e=json.loads(raw)
 except json.JSONDecodeError:return
 events.append(e);last=time.monotonic();typ=e.get('type');i=e.get('item',{});it=i.get('type','')
 if typ=='turn.completed':usage=e.get('usage',{})
 if typ=='item.started' and it=='mcp_tool_call':
  calls+=1
  usage_read()
  if not declaration_verified:reason=reason or 'scientific tool started without verified hosted declaration'
  if i.get('tool')=='save_domain_judgment':saves+=1
  if calls>16:reason=reason or 'tool-start limit exceeded'
 if typ=='item.completed' and it=='mcp_tool_call':
  completed+=1;result=(i.get('result') or {}).get('structured_content') or {};outcome=result.get('outcome') if isinstance(result,dict) else None
  if i.get('tool')=='save_domain_judgment' and (i.get('status')=='failed' or outcome!='success'):
   rejections+=1
   if rejections>=2:reason=reason or 'two rejected submissions'
  if i.get('tool')=='save_domain_judgment' and outcome=='success':reason=reason or 'accepted D3 checkpoint'
  if completed>=16:reason=reason or '16 completed tools'
 if it=='command_execution':reason=reason or 'unapproved shell access'
 print(case,typ,it,i.get('tool',''),'calls',calls,'rejections',rejections,flush=True)
with (root/'stderr.log').open('wb') as err,(root/'events.jsonl').open('wb') as log:
 proc=subprocess.Popen(cmd,cwd=root/'workspace',env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=err,start_new_session=True);assert proc.stdin and proc.stdout;proc.stdin.write((root/'prompt.txt').read_bytes());proc.stdin.close();sel=selectors.DefaultSelector();sel.register(proc.stdout,selectors.EVENT_READ);print(case,'LAUNCHED',proc.pid,flush=True)
 while proc.poll() is None:
  for key,_ in sel.select(1):
   raw=key.fileobj.readline()
   if raw:log.write(raw);log.flush();event(raw)
  usage_read()
  if usage.get('input_tokens',0)>=500000:reason=reason or 'total input threshold'
  if usage.get('input_tokens',0)-usage.get('cached_input_tokens',0)>=100000:reason=reason or 'uncached input threshold'
  if usage.get('output_tokens',0)>=5000:reason=reason or 'output threshold'
  if time.monotonic()-start>=480:reason=reason or 'wall threshold'
  if time.monotonic()-last>=120:reason=reason or 'idle threshold'
  if reason and proc.poll() is None:
   sampled=dict(usage);os.killpg(proc.pid,signal.SIGTERM)
   try:proc.wait(timeout=5)
   except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait()
 for raw in proc.stdout:log.write(raw);event(raw)
usage_read();totals={k:sum(r['usage'].get(k,0) for r in records.values()) for k in ['input_tokens','cached_input_tokens','cache_write_input_tokens','output_tokens','reasoning_output_tokens','total_tokens']}
response=root/'response.txt';run={'case':case,'code_sha':m['code_sha'],'command':cmd,'started_at_utc':started,'completed_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'elapsed_seconds':round(time.monotonic()-start,2),'exit_code':proc.returncode,'stop_reason':reason,'tool_calls_started':calls,'tool_calls_completed':completed,'save_calls_started':saves,'rejected_submissions':rejections,'usage':totals,'generation_count':len(records),'monitor_snapshot_at_stop':sampled,'recorded_input_overshoot':max(0,totals['input_tokens']-500000),'recorded_uncached_overshoot':max(0,totals['input_tokens']-totals['cached_input_tokens']-100000),'recorded_output_overshoot':max(0,totals['output_tokens']-5000),'response_sha256':hashlib.sha256(response.read_bytes()).hexdigest() if response.exists() else None,'hosted_declaration_verified':declaration_verified,'model_code_tool_calls':code_calls,'no_manual_repairs':True,'no_invocation_retry':True}
(root/'run.json').write_text(json.dumps(run,indent=2)+'\n')
for f in ['run.json','events.jsonl','durable-token-usage-records.json','response.txt','hosted-input-declaration.json']:
 if (root/f).exists():(out/f).write_bytes((root/f).read_bytes())
print('FROZEN',json.dumps(run),flush=True)
