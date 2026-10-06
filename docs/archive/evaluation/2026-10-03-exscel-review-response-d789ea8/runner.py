from pathlib import Path
import json,os,subprocess,selectors,time,signal,hashlib
root=Path(__file__).parent/'exscel-review-response-d789ea8';prompt=(root/'input.txt').read_text();criteria=json.loads((root/'criteria.json').read_text());assert hashlib.sha256(prompt.encode()).hexdigest()==criteria['input_sha256']
cmd=['codex','exec','--strict-config','--ignore-rules','--skip-git-repo-check','-m','gpt-6-luna','-c','model_reasoning_effort="medium"','--json','-o',str(root/'response.txt'),'-'];(root/'command.json').write_text(json.dumps(cmd,indent=2));start=time.monotonic();last=start;stop=None;records={};calls=0

def usage():
 for path in (root/'home/sessions').rglob('*.jsonl'):
  for line in path.read_text().splitlines():
   try:r=json.loads(line)
   except ValueError:continue
   if r.get('type')=='token_usage_record':records[r['payload']['response_id']]=r['payload']
 return {k:sum(v['usage'].get(k,0) for v in records.values()) for k in ['input_tokens','cached_input_tokens','output_tokens','reasoning_output_tokens']}
with (root/'events.jsonl').open('wb') as log,(root/'stderr.log').open('wb') as err:
 p=subprocess.Popen(cmd,cwd=root/'workspace',env={**os.environ,'CODEX_HOME':str(root/'home')},stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=err,start_new_session=True);p.stdin.write(prompt.encode());p.stdin.close();sel=selectors.DefaultSelector();sel.register(p.stdout,selectors.EVENT_READ)
 while p.poll() is None:
  for _,_ in sel.select(1):
   raw=p.stdout.readline()
   if raw:
    log.write(raw);log.flush();last=time.monotonic();r=json.loads(raw);i=r.get('item',{})
    if r.get('type')=='item.started' and i.get('type') in ['mcp_tool_call','command_execution','web_search']:calls+=1
  u=usage();now=time.monotonic()
  stop=next((why for reached,why in [(calls>0,'unexpected tool'),(u['output_tokens']>=4000,'output guard'),(now-start>=300,'wall guard'),(now-last>=120,'idle guard')] if reached),None)
  if stop:break
 if p.poll() is None:
  os.killpg(p.pid,signal.SIGTERM)
  try:p.wait(timeout=5)
  except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait()
 for raw in p.stdout:log.write(raw)
 sel.close()
u=usage();metadata=[]
for path in (root/'home/sessions').rglob('*.jsonl'):
 for l in path.read_text().splitlines():
  r=json.loads(l)
  if r.get('type')=='turn_context':metadata.append({k:r['payload'].get(k) for k in ['model','effort','turn_id']})
summary={'exit_code':p.returncode,'stop':stop,'elapsed_seconds':time.monotonic()-start,'tool_calls':calls,'usage':u,'uncached_input_tokens':u['input_tokens']-u['cached_input_tokens'],'response_ids':list(records),'model_settings':metadata,'output_overshoot':max(0,u['output_tokens']-4000),'one_invocation':True,'no_retry':True};(root/'usage.json').write_text(json.dumps(summary,indent=2));(root/'provider-response-usage.json').write_text(json.dumps(records,indent=2));print(json.dumps(summary,indent=2))
