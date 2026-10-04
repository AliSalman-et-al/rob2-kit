"""One authorized frozen citation-fidelity response; never retry."""
from __future__ import annotations
import hashlib,json,os,selectors,signal,subprocess,time,tomllib
from pathlib import Path
from diagnostic_evidence_preflight import launch_checked
R=Path(__file__).resolve().parent

def sha(p:Path)->str:return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p:Path,x:object)->None:p.write_text(json.dumps(x,indent=2)+'\n')
def run_arm(arm:str,m:dict)->None:
 spec=m['arms'][arm];work=Path(spec['work']);home=work/'home';cfg=tomllib.loads((home/'config.toml').read_text())
 assert not (R/(arm+'-run.json')).exists(),'No retry/continuation'
 baseline_files=set((home/'sessions').rglob('*.jsonl'))
 assert {str(p):sha(p) for p in baseline_files}==m['existing_rollout_hashes']
 assert (cfg['model'],cfg['model_reasoning_effort'])==('gpt-6-luna','medium')
 assert not cfg.get('mcp_servers') and all(v is False for v in cfg['features'].values())
 assert sha(home/'config.toml')==spec['config_sha256'] and sha(R/(arm+'-input.txt'))==spec['input_sha256']
 assert sha(work/'instructions.md')==m['instructions_sha256']
 command=['codex','exec','--strict-config','--ignore-rules','--skip-git-repo-check','-s','read-only','-m','gpt-6-luna','-c','model_reasoning_effort="medium"','--json','-o',str(R/(arm+'-response.txt')),'-']
 write(R/(arm+'-command.json'),command)
 assert command[command.index('-m')+1]==m['model']=='gpt-6-luna'
 records={};model_context=[];tool_calls=set();final_messages=0;stop=None;buffer=b'';started=last=time.monotonic()
 def telemetry():
  nonlocal stop
  files=[p for p in (home/'sessions').rglob('*.jsonl') if p not in baseline_files]
  if len(files)>1:stop=stop or 'multiple sessions';return
  for file in files:
   for line in file.read_text().splitlines():
    try:row=json.loads(line)
    except ValueError:continue
    payload=row.get('payload',{})
    if row.get('type')=='token_usage_record':records[payload['response_id']]={'timestamp':row.get('timestamp'),**payload}
    if row.get('type')=='turn_context':
     context={'model':payload.get('model'),'effort':payload.get('effort')}
     if context not in model_context:model_context.append(context)
     if context!={'model':'gpt-6-luna','effort':'medium'}:stop=stop or 'model mismatch'
    if row.get('type')=='response_item' and payload.get('type') in {'function_call','custom_tool_call'}:tool_calls.add(payload.get('call_id','unknown'))
 def usage():return {key:sum(row['usage'].get(key,0) for row in records.values()) for key in ['input_tokens','cached_input_tokens','output_tokens','reasoning_output_tokens']}
 def check():
  nonlocal stop
  telemetry();now=time.monotonic();u=usage()
  if tool_calls:stop=stop or 'unexpected tool call'
  elif final_messages>1:stop=stop or 'multiple final messages'
  elif len(records)>1:stop=stop or 'more than one provider response'
  elif u['output_tokens']>=2000:stop=stop or 'output limit'
  elif now-started>=300:stop=stop or 'wall limit'
  elif now-last>=120:stop=stop or 'idle limit'
  return stop
 def consume(chunk:bytes):
  nonlocal buffer,last,stop,final_messages
  log.write(chunk);log.flush();buffer+=chunk
  while b'\n' in buffer:
   line,buffer=buffer.split(b'\n',1)
   if not line.strip():continue
   row=json.loads(line);last=time.monotonic();item=row.get('item',{})
   if item.get('type') in {'command_execution','mcp_tool_call','web_search','image_view','collab_tool_call'}:tool_calls.add(item.get('id','unknown'))
   if row.get('type')=='item.completed' and item.get('type')=='agent_message':final_messages+=1
 write(R/(arm+'-run.json'),{'state':'started','no_retry':True,'command':command})
 with (R/(arm+'-events.jsonl')).open('wb') as log,(R/(arm+'-stderr.log')).open('wb') as err:
  process=launch_checked(command,manifest_path=R/(arm+'-evidence-manifest.json'),input_path=R/(arm+'-input.txt'),receipt_path=R/(arm+'-launch-preflight.json'),expected_manifest_sha256=spec['evidence_manifest_sha256'],cwd=work/'workspace',env={**os.environ,'CODEX_HOME':str(home)},stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=err,start_new_session=True)
  process.stdin.write((R/(arm+'-input.txt')).read_bytes());process.stdin.close();os.set_blocking(process.stdout.fileno(),False);sel=selectors.DefaultSelector();sel.register(process.stdout,selectors.EVENT_READ)
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
 u=usage();result={'exit_code':process.returncode,'stop':stop,'elapsed_seconds':time.monotonic()-started,'tool_calls':len(tool_calls),'final_messages':final_messages,'provider_response_count':len(records),'usage':u,'uncached_input_tokens':u['input_tokens']-u['cached_input_tokens'],'model_context':model_context,'output_overshoot':max(0,u['output_tokens']-2000),'guards':'reactive; not provider-enforced token cap','retry_or_continuation':False}
 write(R/(arm+'-durable-token-usage-records.json'),list(records.values()));write(R/(arm+'-effective-model.json'),model_context);write(R/(arm+'-run.json'),result)
 print(json.dumps({arm:result}),flush=True)

def main():
 m=json.loads((R/'manifest.json').read_text())
 assert m['limits']=={'calls':1,'responses_per_arm':1,'tools':0,'output_tokens_per_arm':2000,'wall_seconds_per_arm':300,'idle_seconds_per_arm':120,'input_telemetry_only':True}
 assert sha(R/'private-criteria.md')==m['private_criteria_sha256']
 assert sha(Path(__file__))==m['runner_sha256']
 assert not (R/'answer-freeze.json').exists()
 run_arm('panel',m)
 for path,h in m['existing_rollout_hashes'].items():assert sha(Path(path))==h
 frozen={name:sha(R/('panel-'+name)) for name in ['response.txt','events.jsonl','run.json','durable-token-usage-records.json'] if (R/('panel-'+name)).exists()}
 write(R/'answer-freeze.json',frozen)
 print('Output frozen before adjudication.',flush=True)
if __name__=='__main__':main()
