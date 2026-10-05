import asyncio,hashlib,json,os,pathlib,subprocess,sys,time
from fastmcp import Client
from rob2_kit.interfaces.mcp.server import mcp
from scripts.diagnostic_evidence_preflight import launch_checked
D=pathlib.Path('/home/ali/Documents/Codex/2026-10-02/task-4/diagnostics/avatar-d4-guidance-pair')
A=D/sys.argv[1];turn=int(sys.argv[2]);sha=lambda b:hashlib.sha256(b).hexdigest()
if turn > 1:
 if len(sys.argv) != 4 or not sys.argv[3].strip():
  raise ValueError('Resume requires a nonempty exact original session ID before any launch')
 original=[json.loads(line) for line in (A/'turn-1.jsonl').read_text().splitlines() if line]
 expected=next(row['thread_id'] for row in original if row['type']=='thread.started')
 if sys.argv[3] != expected:
  raise ValueError('Resume session must equal this arm original frozen thread ID')
 if not (A/'operator-approval.stdout').exists() or '\"approved\": true' not in (A/'operator-approval.stdout').read_text():
  raise ValueError('Exact normal ProposalReview approval must succeed before resume')

def write(p,x):p.write_text(json.dumps(x,indent=2)+'\n')
os.environ['ROB2_WORKSPACE']=str(A/'workspace')
if turn==1:
 frozen=json.loads((D/'prelaunch-freeze.json').read_text())
 for name,h in frozen.items():
  # Earlier arm's mutable state may progress independently after both inputs were frozen.
  if name.startswith(('old/workspace/','new/workspace/')):continue
  assert sha((D/name).read_bytes())==h,name
 async def verify():
  async with Client(mcp) as c:
   s=(await c.call_tool('list_sources',{'trial_id':'banovic26-avatar-2024'})).structured_content
   assert s['data']['sources']==json.loads((D/'sources.json').read_text())['data']['sources']
   st=(await c.call_tool('get_status',{})).structured_content
   assert st['head']['phase']=='proposal' and st['head']['state_revision']==1
   write(A/'prelaunch-native-verification.json',{'sources':s,'status':st})
 asyncio.run(verify())
 inp=A/'model-input.txt';manifest=A/'evidence-manifest.json'
 cmd=['/home/ali/.nvm/versions/node/v24.21.0/bin/codex','exec','--json','--skip-git-repo-check','-m','gpt-6-luna','-c','model_reasoning_effort="medium"','-C',str(A/'workspace'),'-o',str(A/f'turn-{turn}-final.txt'),'-']
else:
 session=sys.argv[3];inp=A/f'model-input-{turn}.txt'
 inp.write_text('Continue the assessment in this same session using get_status and its canonical next action, following the normal rob2-kit guidance.\n')
 m=json.loads((A/'evidence-manifest.json').read_text());m['input_sha256']=sha(inp.read_bytes());manifest=A/f'evidence-manifest-{turn}.json';write(manifest,m)
 cmd=['/home/ali/.nvm/versions/node/v24.21.0/bin/codex','exec','resume','--json','--skip-git-repo-check','-m','gpt-6-luna','-c','model_reasoning_effort="medium"','-o',str(A/f'turn-{turn}-final.txt'),session,'-']
env={**os.environ,'CODEX_HOME':str(A/'home')}
write(A/f'launch-{turn}.json',{'command':cmd,'started_at':time.time(),'code_commit':json.loads((D/'research-design.json').read_text())['runtime_commit'],'input_sha256':sha(inp.read_bytes()),'config_sha256':sha((A/'home/config.toml').read_bytes()),'session_policy':'two independent sessions only; generic continuations in same session','operator_authorization':'delegated paired diagnostic; normal exact ProposalReview only'})
p=launch_checked(cmd,manifest_path=manifest,input_path=inp,evidence_bundle_path=D/'native-evidence.bundle',receipt_path=A/f'launch-preflight-{turn}.json',expected_manifest_sha256=sha(manifest.read_bytes()),stdin=open(inp,'rb'),stdout=open(A/f'turn-{turn}.jsonl','wb'),stderr=open(A/f'turn-{turn}.stderr','wb'),cwd=A/'workspace',env=env,start_new_session=True)
write(A/f'process-{turn}.json',{'pid':p.pid,'turn':turn,'started_at':time.time()});print('LAUNCHED',A.name,turn,p.pid,flush=True)
rc=p.wait();write(A/f'exit-{turn}.json',{'returncode':rc,'finished_at':time.time()});print('EXIT',A.name,turn,rc,flush=True)
