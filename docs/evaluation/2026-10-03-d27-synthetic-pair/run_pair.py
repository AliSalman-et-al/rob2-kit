from pathlib import Path
import hashlib,json,os,queue,shutil,signal,subprocess,sys,threading,time,tomllib
ROOT=Path(__file__).resolve().parent
REPO=ROOT.parent.parent/'rob2-kit'
SOURCE=REPO/'docs/evaluation/2026-10-03-d27-synthetic-pair'
sys.path.insert(0,str(REPO/'scripts'))
from diagnostic_evidence_preflight import launch_checked
SHA='312b478b688ee73fc28d20d81f5340d568614967'
assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip()==SHA
assert not (ROOT/'protocol.json').exists()
files=['baseline-input.txt','current-input.txt','baseline-manifest.json','current-manifest.json','frozen-model-config.toml','private-adjudication-rubric.json']
config=(SOURCE/'frozen-model-config.toml').read_bytes();settings=tomllib.loads(config.decode());assert (settings['model'],settings['model_reasoning_effort'])==('gpt-6-luna','medium') and 'mcp_servers' not in settings
protocol={'frozen_source_commit':SHA,'authorization':'Parent authorizes at most two short LunaMedium responses for this explicitly authorized synthetic mechanism iteration; no third response or native run.','order':['baseline','current'],'model':'gpt-6-luna','effort':'medium','maximum_invocations':2,'no_retry':True,'output_tokens_guard':2000,'wall_seconds_guard':300,'idle_seconds_guard':120,'tools_allowed':0,'input_tokens':'telemetry; complete short fictional facts/guidance approximately3.6k tokens per arm at3chars/token','freeze_both_outputs_before_adjudication':True,'source_hashes':{n:hashlib.sha256((SOURCE/n).read_bytes()).hexdigest() for n in files},'new_model_hint':False,'adjudication_blinding':'Unblinded AI scientific-warrant review after both freezes; private criteria never supplied.'}
(ROOT/'protocol.json').write_text(json.dumps(protocol,indent=2)+'\n')
for arm in protocol['order']:
 r=ROOT/arm;r.mkdir();home=r/'home';home.mkdir()
 for name in ['auth.json','models_cache.json']:
  f=ROOT.parent/'host-exam-d5-6d0ac5e/home'/name
  if f.exists():shutil.copyfile(f,home/name)
 (home/'config.toml').write_bytes(config)
 (r/'input.txt').write_bytes((SOURCE/f'{arm}-input.txt').read_bytes())
 (r/'evidence-manifest.json').write_bytes((SOURCE/f'{arm}-manifest.json').read_bytes())
 assert not list((home/'sessions').rglob('*.jsonl'))
(ROOT/'runner-freeze.json').write_text(json.dumps({'runner_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'protocol_sha256':hashlib.sha256((ROOT/'protocol.json').read_bytes()).hexdigest()},indent=2)+'\n')

def run_one(arm):
 r=ROOT/arm;records={};models=[];calls=set();reason=None
 command=['codex','exec','--strict-config','--ignore-rules','--skip-git-repo-check','-m','gpt-6-luna','-c','model_reasoning_effort="medium"','--json','-o',str(r/'response.txt'),'-']
 (r/'command.json').write_text(json.dumps(command,indent=2)+'\n')
 # One durable intent per arm prevents rerun even if this process is interrupted.
 (r/'invocation-intent.json').write_text(json.dumps({'arm':arm,'invocation':1,'no_retry':True})+'\n')
 def read_usage():
  rollouts=list((r/'home/sessions').rglob('*.jsonl'));assert len(rollouts)<=1
  for path in rollouts:
   for line in path.read_text().splitlines():
    try:row=json.loads(line)
    except ValueError:continue
    p=row.get('payload',{})
    if row.get('type')=='token_usage_record':records[p['response_id']]=p
    if row.get('type')=='response_item' and p.get('type') in ['custom_tool_call','function_call']:calls.add(p.get('call_id',json.dumps(p,sort_keys=True)))
  return {k:sum(rec['usage'].get(k,0) for rec in records.values()) for k in ['input_tokens','cached_input_tokens','output_tokens','reasoning_output_tokens']}
 started=last=time.monotonic();stream=queue.Queue()
 with (r/'events.jsonl').open('wb') as log,(r/'stderr.log').open('wb') as err:
  # Immediately before each new process: exact frozen hash plus declared source coverage.
  expected=protocol['source_hashes'][f'{arm}-manifest.json']
  assert hashlib.sha256((r/'input.txt').read_bytes()).hexdigest()==protocol['source_hashes'][f'{arm}-input.txt']
  assert (r/'home/config.toml').read_bytes()==config
  p=launch_checked(command,manifest_path=r/'evidence-manifest.json',input_path=r/'input.txt',receipt_path=r/'launch-preflight.json',expected_manifest_sha256=expected,cwd=r,env={**os.environ,'CODEX_HOME':str(r/'home')},stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=err,start_new_session=True)
  p.stdin.write((r/'input.txt').read_bytes());p.stdin.close()
  def reader():
   for raw in p.stdout:stream.put(raw)
   stream.put(None)
  t=threading.Thread(target=reader,daemon=True);t.start()
  def consume(raw):
   nonlocal last
   log.write(raw);log.flush();last=time.monotonic()
   try:event=json.loads(raw)
   except ValueError:return
   item=event.get('item',{})
   if event.get('type')=='item.started' and item.get('type') in ['mcp_tool_call','command_execution','web_search','custom_tool_call']:calls.add(item.get('id',json.dumps(item,sort_keys=True)))
  while p.poll() is None:
   try:raw=stream.get(timeout=0.5)
   except queue.Empty:raw=None
   if raw:consume(raw)
   u=read_usage();now=time.monotonic()
   reason=next((s for ok,s in [(bool(calls),'unexpected tool'),(u['output_tokens']>=2000,'output guard'),(now-started>=300,'wall guard'),(now-last>=120,'idle guard')] if ok),None)
   if reason:break
  if p.poll() is None:
   os.killpg(p.pid,signal.SIGTERM)
   try:p.wait(timeout=5)
   except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait()
  t.join(timeout=5)
  while not stream.empty():
   raw=stream.get_nowait()
   if raw:consume(raw)
 u=read_usage()
 for path in (r/'home/sessions').rglob('*.jsonl'):
  for line in path.read_text().splitlines():
   try:row=json.loads(line)
   except ValueError:continue
   if row.get('type')=='turn_context':models.append({k:row['payload'].get(k) for k in ['model','effort','turn_id']})
 (r/'provider-response-usage.json').write_text(json.dumps(records,indent=2)+'\n')
 (r/'model-settings.json').write_text(json.dumps(models,indent=2)+'\n')
 valid=bool(models) and all((m['model'],m['effort'])==('gpt-6-luna','medium') for m in models)
 summary={'arm':arm,'one_invocation':True,'no_retry':True,'exit_code':p.returncode,'stop_reason':reason,'elapsed_seconds':time.monotonic()-started,'tool_calls':len(calls),'usage':u,'uncached_input_tokens':u['input_tokens']-u['cached_input_tokens'],'output_overshoot':max(0,u['output_tokens']-2000),'response_file_exists':(r/'response.txt').exists(),'model_verified':valid,'model_settings':models,'usage_response_ids':list(records)}
 (r/'run.json').write_text(json.dumps(summary,indent=2)+'\n')
 print(json.dumps(summary),flush=True)
 return summary
results=[]
for arm in protocol['order']:results.append(run_one(arm))
frozen={}
for arm in protocol['order']:
 for f in (ROOT/arm).iterdir():
  if f.is_file():frozen[str(f.relative_to(ROOT))]=hashlib.sha256(f.read_bytes()).hexdigest()
(ROOT/'both-outputs-frozen.json').write_text(json.dumps({'scientific_adjudication_started':False,'hashes':frozen,'results':results},indent=2)+'\n')
print('BOTH_OUTPUTS_FROZEN_NO_FURTHER_INVOCATIONS',flush=True)
