"""Supported no-inference fork preflight; preserve originals and never fabricate state."""
from __future__ import annotations
import hashlib,json,os,selectors,shutil,subprocess,time,sqlite3
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];R=Path(__file__).parent;D=ROOT.parent/'diagnostics/gupta-fork-continuation-20261004';OLD=ROOT.parent/'diagnostics/gupta-validation-fcd83d7';PY='/home/ali/Documents/Codex/2026-10-02/task/rob2-kit/.venv/bin/python'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,v):p.write_text(json.dumps(v,indent=2)+'\n')
assert not D.exists(),'No retry of preflight'
D.mkdir();protected=[p for p in (OLD/'workspace').rglob('*') if p.is_file()]+list((OLD/'home/sessions').rglob('*.jsonl'))+[OLD/'budget-state.json',OLD/'usage.json',OLD/'home/config.toml']
hashes={str(p):sha(p) for p in protected};shutil.copytree(OLD/'workspace',D/'workspace')
for p in (OLD/'workspace').rglob('*'):
 if p.is_file():assert sha(p)==sha(D/'workspace'/p.relative_to(OLD/'workspace'))
code_sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip();code=D/'code';code.mkdir()
archive=subprocess.Popen(['git','archive',code_sha,'src','scripts','pyproject.toml'],cwd=ROOT,stdout=subprocess.PIPE)
subprocess.run(['tar','-x','-C',str(code)],stdin=archive.stdout,check=True);archive.stdout.close();assert archive.wait()==0
subprocess.run([PY,'-m','rob2_kit.interfaces.cli.app','export-skill','--output',str(D/'rob2-assess')],env={**os.environ,'PYTHONPATH':str(code/'src')},check=True,stdout=subprocess.DEVNULL)
skill=D/'rob2-assess/SKILL.md';assert 'what each selected source actually establishes' in skill.read_text()
with sqlite3.connect(f'file:{(D/"workspace/.rob2-kit/canonical.sqlite3").resolve()}?mode=ro',uri=True) as c:state=json.loads(c.execute('SELECT payload FROM workflow_head').fetchone()[0])
assert state['revision']==8 and len(state['domain_records'])==4 and not state.get('trial_closures')
for source in state['batch']['trials'][0]['sources']:assert sha(D/'workspace/.rob2-kit/sources/gupta-2024'/(source['id']+'.bin'))==source['sha256'].removeprefix('sha256:')
features={k:False for k in ['shell_tool','unified_exec','view_image','apps','browser_use','computer_use','sleep_tool','tool_suggest','multi_agent','code_mode']}
config={'model':'gpt-6-luna','model_reasoning_effort':'medium','web_search':'disabled','model_instructions_file':str(skill),'features':features,'mcp_servers':{'rob2':{'command':PY,'args':['-m','rob2_kit.interfaces.cli.app','mcp-codex'],'required':True,'default_tools_approval_mode':'approve','startup_timeout_sec':60,'tool_timeout_sec':90,'env':{'ROB2_WORKSPACE':str(D/'workspace'),'PYTHONPATH':str(code/'src')}}}}
params={'threadId':'01a10362-81a7-7152-b902-cb2149fe85b6','cwd':str(D/'workspace'),'model':'gpt-6-luna','approvalPolicy':'never','sandbox':'read-only','config':config,'excludeTurns':False}
write(R/'fork-parameters.json',params);write(R/'original-preservation.json',hashes)
command=['codex','app-server','--stdio'];write(R/'preflight-command.json',command)
p=subprocess.Popen(command,env={**os.environ,'CODEX_HOME':str(OLD/'home')},stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=(D/'preflight-stderr.log').open('wb'),start_new_session=True)
sel=selectors.DefaultSelector();sel.register(p.stdout,selectors.EVENT_READ);buffer=b'';messages=[]
def request(number,method,params):
 global buffer
 p.stdin.write((json.dumps({'id':number,'method':method,'params':params})+'\n').encode());p.stdin.flush();start=time.monotonic()
 while time.monotonic()-start<60:
  for key,_ in sel.select(.25):
   chunk=os.read(key.fileobj.fileno(),65536)
   if not chunk:raise RuntimeError('app server closed')
   buffer+=chunk
   while b'\n' in buffer:
    line,buffer=buffer.split(b'\n',1)
    if not line.strip():continue
    row=json.loads(line);messages.append(row)
    if row.get('id')==number:return row
 raise RuntimeError('preflight request timeout')
try:
 initialize=request(1,'initialize',{'clientInfo':{'name':'rob2-offline-fork-preflight','version':'1.0'}})
 assert 'result' in initialize,initialize
 p.stdin.write(b'{"method":"initialized"}\n');p.stdin.flush()
 result=request(2,'thread/fork',params);write(D/'raw-fork-response.json',result)
 if 'error' in result:verdict={'success':False,'error':result['error'],'model_calls':0}
 else:
  data=result['result'];thread=data['thread'];tid=thread['id'];assert tid!=params['threadId'];assert data.get('model')=='gpt-6-luna';assert data.get('cwd')==str(D/'workspace')
  turns=[{'id':t.get('id'),'status':t.get('status'),'item_count':len(t.get('items',[]))} for t in thread.get('turns',[])]
  verdict={'success':True,'fork_id':tid,'source_session':params['threadId'],'model':data.get('model'),'cwd':data.get('cwd'),'turns':turns,'model_calls':0,'recovered_latest_turn':any(t['id']=='01a10365-9be4-7110-bde3-69ace622b9b1' for t in turns),'response_metadata':{k:v for k,v in data.items() if k!='thread'}}
  assert verdict['recovered_latest_turn'],'Interrupted turn missing: no-go'
finally:
 p.terminate()
 try:p.wait(timeout=5)
 except subprocess.TimeoutExpired:p.kill();p.wait()
 sel.close();write(D/'preflight-events-private.json',messages)
assert hashes=={str(Path(path)):sha(Path(path)) for path in hashes},'Original changed: no-go'
verdict.update({'originals_unchanged':True,'code_sha':code_sha,'skill_sha256':sha(skill),'workspace_head_sha256':sha(D/'workspace/.rob2-kit/canonical.sqlite3'),'approval_identity':state['proposal_acknowledgment']['identity'],'saved_domains':{k:v['identity'] for k,v in state['domain_records'].items()},'source_snapshot_unchanged':True,'transport':'mcp-codex','staging_path':str(D)})
write(R/'preflight.json',verdict);print(json.dumps({k:verdict[k] for k in ['success','model_calls','originals_unchanged']},indent=2))
