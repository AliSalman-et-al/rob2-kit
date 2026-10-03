from pathlib import Path
import json,hashlib,os,subprocess,selectors,time,signal,sys,tomllib
D=Path(__file__).resolve().parent;root=D/'d5-pair-3f393a0';repo=D/'frozen-d5-pair-3f393a0-code';sys.path.insert(0,str(repo))
from scripts.diagnostic_evidence_preflight import check_manifest,launch_checked
protocol=json.loads((root/'preregistered-private-protocol.json').read_text())
assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()==protocol['code_sha']
assert not subprocess.check_output(['git','status','--porcelain'],cwd=repo)
assert protocol['maximum_invocations']==2 and protocol['no_retry']
for name in protocol['conditions']:
 r=root/name
 assert not (r/'run.json').exists() and not list((r/'home/sessions').rglob('*.jsonl'))
 assert hashlib.sha256((r/'manifest.json').read_bytes()).hexdigest()==protocol['condition_manifest_hashes'][name]
 m=json.loads((r/'manifest.json').read_text());assert (m['model'],m['effort'])==('gpt-6-luna','medium')
 c=tomllib.loads((r/'home/config.toml').read_text());assert (c['model'],c['model_reasoning_effort'])==('gpt-6-luna','medium') and 'mcp_servers' not in c
 check_manifest(r/'evidence-manifest.json',r/'input.txt')
 assert hashlib.sha256((r/'instructions.md').read_bytes()).hexdigest()==m['instructions_sha256']

def run_one(name):
 r=root/name;m=json.loads((r/'manifest.json').read_text());records={};calls=0;models=[];stop=None
 command=['codex','exec','--strict-config','--ignore-rules','--skip-git-repo-check','-m','gpt-6-luna','-c','model_reasoning_effort="medium"','--json','-o',str(r/'response.txt'),'-']
 (r/'command.json').write_text(json.dumps(command,indent=2))
 def usage():
  for path in (r/'home/sessions').rglob('*.jsonl'):
   for line in path.read_text().splitlines():
    try:row=json.loads(line)
    except ValueError:continue
    if row['type']=='token_usage_record':records[row['payload']['response_id']]=row['payload']
  return {k:sum(x['usage'].get(k,0) for x in records.values()) for k in ['input_tokens','cached_input_tokens','output_tokens','reasoning_output_tokens']}
 start=last=time.monotonic()
 with (r/'events.jsonl').open('wb') as log,(r/'stderr.log').open('wb') as err:
  p=launch_checked(command,manifest_path=r/'evidence-manifest.json',input_path=r/'input.txt',receipt_path=r/'launch-preflight.json',expected_manifest_sha256=m['evidence_manifest_sha256'],cwd=r,env={**os.environ,'CODEX_HOME':str(r/'home')},stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=err,start_new_session=True)
  p.stdin.write((r/'input.txt').read_bytes());p.stdin.close();sel=selectors.DefaultSelector();sel.register(p.stdout,selectors.EVENT_READ)
  while p.poll() is None:
   for _,_ in sel.select(1):
    raw=p.stdout.readline()
    if raw:
     log.write(raw);log.flush();last=time.monotonic();row=json.loads(raw);i=row.get('item',{})
     if row['type']=='item.started' and i.get('type') in ['mcp_tool_call','command_execution','web_search']:calls+=1
   u=usage();now=time.monotonic()
   code_calls=sum(1 for path in (r/'home/sessions').rglob('*.jsonl') for line in path.read_text().splitlines() if '"type":"custom_tool_call"' in line or '"type": "custom_tool_call"' in line)
   stop=next((why for reached,why in [(calls+code_calls>0,'unexpected tool'),(u['output_tokens']>=4000,'output guard'),(now-start>=300,'wall guard'),(now-last>=120,'idle guard')] if reached),None)
   if stop:break
  if p.poll() is None:
   os.killpg(p.pid,signal.SIGTERM)
   try:p.wait(timeout=5)
   except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait()
  for raw in p.stdout:log.write(raw)
  sel.close()
 u=usage()
 for path in (r/'home/sessions').rglob('*.jsonl'):
  for line in path.read_text().splitlines():
   row=json.loads(line)
   if row['type']=='turn_context':models.append({k:row['payload'].get(k) for k in ['model','effort','turn_id']})
 assert all((v['model'],v['effort'])==('gpt-6-luna','medium') for v in models)
 summary={'condition':name,'one_invocation':True,'no_retry':True,'exit_code':p.returncode,'stop_reason':stop,'elapsed_seconds':time.monotonic()-start,'native_tool_calls':calls,'custom_tool_calls':code_calls,'usage':u,'uncached_input_tokens':u['input_tokens']-u['cached_input_tokens'],'output_overshoot':max(0,u['output_tokens']-4000),'model_settings':models}
 (r/'run.json').write_text(json.dumps(summary,indent=2));(r/'provider-usage.json').write_text(json.dumps(records,indent=2))
 return summary

results=[]
for name in protocol['conditions']:results.append(run_one(name))
frozen={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for name in protocol['conditions'] for p in (root/name).iterdir() if p.is_file()}
(root/'both-outputs-frozen.json').write_text(json.dumps({'scientific_evaluation_started':False,'hashes':frozen,'results':results},indent=2))
print(json.dumps(results,indent=2))
