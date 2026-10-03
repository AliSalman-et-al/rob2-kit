"""One native CLI turn; no retry/resume; freeze controls before creating child."""
from __future__ import annotations
import hashlib,json,os,selectors,signal,subprocess,time,tomllib
from pathlib import Path
from diagnostic_evidence_preflight import launch_checked
from workflow_completion import tool_feedback
R=Path(__file__).resolve().parent;CODE=R.parent/'real-reading-code'

def run():
 assert not (R/'run.json').exists() and not list((R/'home/sessions').rglob('*.jsonl')),'No retry or continuation'
 m=json.loads((R/'manifest.json').read_text());cfg=tomllib.loads((R/'home/config.toml').read_text())
 assert (cfg['model'],cfg['model_reasoning_effort'])==('gpt-6-luna','medium')
 assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=CODE,text=True).strip()==m['code_sha']
 assert not subprocess.check_output(['git','status','--porcelain'],cwd=CODE)
 for name,key in [('expected-private.json','expected_sha256'),('prompt.txt','prompt_sha256'),('instructions.md','instructions_sha256'),('home/config.toml','config_sha256'),('private-source-packet.bin','source_packet_sha256')]:assert hashlib.sha256((R/name).read_bytes()).hexdigest()==m[key]
 for name,source in m['source_origins'].items():assert hashlib.sha256((R/'workspace/input/gupta-2024'/name).read_bytes()).hexdigest()==source['sha256']
 assert hashlib.sha256((R.parent/'codex-integration-release/dist/rob2_kit-0.11.0-py3-none-any.whl').read_bytes()).hexdigest()==m['installed_wheel_sha256']
 command=['codex','exec','--strict-config','--ignore-rules','--skip-git-repo-check','-s','read-only','-m','gpt-6-luna','-c','model_reasoning_effort="medium"','-c','features.code_mode={enabled=true,direct_only_tool_namespaces=["mcp__rob2"]}','--json','-o',str(R/'response.txt'),'-']
 records={};calls=set();session=None;stop=None;start=last=time.monotonic();buffer=b''
 (R/'run.json').write_text(json.dumps({'state':'started','command':command,'no_retry':True,'single_cli_turn':True},indent=2)+'\n')
 def telemetry():
  nonlocal stop
  files=list((R/'home/sessions').rglob('*.jsonl'))
  if len(files)>1:stop=stop or 'multiple sessions';return
  for file in files:
   for line in file.read_text().splitlines():
    try:row=json.loads(line)
    except ValueError:continue
    p=row.get('payload',{})
    if row.get('type')=='token_usage_record':records[p['response_id']]={'timestamp':row.get('timestamp'),**p}
    elif row.get('type')=='response_item' and p.get('type')=='custom_tool_call':calls.add('wrapper:'+p['call_id'])
    elif row.get('type')=='turn_context':
     meta={k:p.get(k) for k in ['model','effort']};(R/'effective-model.json').write_text(json.dumps(meta,indent=2)+'\n')
     if meta['model']!='gpt-6-luna' or meta['effort']!='medium':stop=stop or 'model/effort mismatch'
 def usage():return {k:sum(r['usage'].get(k,0) for r in records.values()) for k in ['input_tokens','cached_input_tokens','output_tokens','reasoning_output_tokens']}
 def check():
  nonlocal stop
  telemetry();u=usage();now=time.monotonic()
  checks=[(len(calls)>=8,'tool limit'),(u['output_tokens']>=2000,'output limit'),(now-start>=240,'wall limit'),(now-last>=90,'idle limit')]
  stop=stop or next((reason for reached,reason in checks if reached),None)
  (R/'usage-live.json').write_text(json.dumps({'calls':len(calls),'usage':u,'elapsed':now-start,'stop':stop},indent=2)+'\n');return stop
 with (R/'events.jsonl').open('wb') as log,(R/'stderr.log').open('wb') as err:
  p=launch_checked(command,manifest_path=R/'evidence-manifest.json',input_path=R/'private-source-packet.bin',receipt_path=R/'launch-preflight.json',expected_manifest_sha256=m['evidence_manifest_sha256'],cwd=R/'workspace',env={**os.environ,'CODEX_HOME':str(R/'home')},stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=err,start_new_session=True)
  p.stdin.write((R/'prompt.txt').read_bytes());p.stdin.close();os.set_blocking(p.stdout.fileno(),False);sel=selectors.DefaultSelector();sel.register(p.stdout,selectors.EVENT_READ)
  def consume(chunk):
   nonlocal buffer,last,stop,session
   log.write(chunk);log.flush();buffer+=chunk
   while b'\n' in buffer:
    line,buffer=buffer.split(b'\n',1)
    if not line.strip():continue
    row=json.loads(line);last=time.monotonic();i=row.get('item',{})
    if row.get('type')=='thread.started':
     if session is not None and session!=row['thread_id']:stop=stop or 'session changed'
     session=row['thread_id']
    if i.get('type')=='command_execution':stop=stop or 'unexpected shell'
    if row.get('type')=='item.started' and i.get('type')=='mcp_tool_call':calls.add('mcp:'+i['id'])
    if row.get('type')=='item.completed' and i.get('type')=='mcp_tool_call':
     feedback=tool_feedback(i)
     if feedback.fingerprint:stop=stop or 'tool feedback: '+feedback.kind
  try:
   while p.poll() is None:
    for key,_ in sel.select(.25):
     chunk=os.read(key.fileobj.fileno(),65536)
     if chunk:consume(chunk)
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
    consume(chunk)
   sel.close();check()
 elapsed=time.monotonic()-start;u=usage();(R/'durable-token-usage-records.json').write_text(json.dumps(list(records.values()),indent=2)+'\n')
 result={'exit_code':p.returncode,'stop':stop,'session':session,'cli_turns':1,'provider_response_count':len(records),'elapsed_seconds':elapsed,'tool_calls':len(calls),'tool_call_ids':sorted(calls),'usage':u,'uncached_input_tokens':u['input_tokens']-u['cached_input_tokens'],'output_overshoot':max(0,u['output_tokens']-2000),'tool_overshoot':max(0,len(calls)-8),'reactive_guards':True,'retry_or_continuation':False};(R/'run.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
if __name__=='__main__':run()
