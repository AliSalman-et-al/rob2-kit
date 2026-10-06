"""Operator diagnostic: one cumulative budget; researcher acknowledgment stays outside."""
from __future__ import annotations
import argparse,hashlib,json,os,selectors,signal,subprocess,time,tomllib
from pathlib import Path
from typing import Any
from diagnostic_evidence_preflight import launch_checked,check_manifest
from workflow_completion import Turn,drive,finalized_artifact
from rob2_kit.application.status import get_status

ROOT=Path(__file__).resolve().parent
CODE=ROOT.parent/'frozen-gupta-validation-fcd83d7'
PYTHON='/home/ali/Documents/Codex/2026-10-02/task/rob2-kit/.venv/bin/python'

class Budget:
    def __init__(self,state:dict[str,Any]|None=None,*,clock=time.time):
        self.clock=clock;self.state=state or {'start':clock(),'last':clock(),'turns':0,'calls':[],'records':{},'previous_error':None,'identical':0,'no_progress':0,'stop':None,'session':None,'events':[]}
    def usage(self):
        return {k:sum(r['usage'].get(k,0) for r in self.state['records'].values()) for k in ['input_tokens','cached_input_tokens','output_tokens','reasoning_output_tokens']}
    def consume(self,row):
        s=self.state;s['last']=self.clock();item=row.get('item',{})
        if row.get('type')=='thread.started':
            sid=row['thread_id']
            if s['session'] is not None and sid!=s['session']:s['stop']='session changed'
            s['session']=sid
        if row.get('type')=='item.started' and item.get('type')=='mcp_tool_call':
            identity=f"{s['turns']}:{item['id']}"
            if identity not in s['calls']:s['calls'].append(identity)
        if item.get('type')=='command_execution':s['stop']='unexpected model shell access'
        if row.get('type')=='item.completed' and item.get('type')=='mcp_tool_call':
            result=item.get('result') or {};payload=result.get('structured_content') or {}
            if item.get('status')=='failed' or item.get('error') or payload.get('outcome') in ['error','condition','repair']:
                # Exclude counters and revisions from identity; retain error content and paths.
                semantic={k:v for k,v in payload.items() if k not in ['head','counters']}
                error=json.dumps([item.get('tool'),semantic or result,item.get('error')],sort_keys=True)
                s['identical']=s['identical']+1 if error==s['previous_error'] else 1;s['previous_error']=error
            else:s['identical']=0;s['previous_error']=None
    def boundary(self,before,after):
        keys=['phase','state_revision','continuation','main_report_reading','host_progress']
        progress=any(before.get(k)!=after.get(k) for k in keys)
        self.state['no_progress']=0 if progress else self.state['no_progress']+1
        return progress
    def check(self):
        s=self.state;u=self.usage();elapsed=self.clock()-s['start'];idle=self.clock()-s['last']
        checks=[(elapsed>=1200,'cumulative wall limit'),(idle>=180,'idle limit'),(len(s['calls'])>=80,'cumulative tool limit'),(u['output_tokens']>=15000,'cumulative output limit'),(s['identical']>=2,'repeated identical error'),(s['no_progress']>=2,'two consecutive no-progress boundaries')]
        s['stop']=s['stop'] or next((why for hit,why in checks if hit),None);return s['stop']
    def begin_turn(self):
        if self.check():raise RuntimeError(self.state['stop'])
        if self.state['turns']>=3:raise RuntimeError('total three-turn allowance exhausted')
        self.state['turns']+=1
    def remaining(self):return max(0,1200-(self.clock()-self.state['start']))


def preflight():
    m=json.loads((ROOT/'manifest.json').read_text());cfg=tomllib.loads((ROOT/'home/config.toml').read_text())
    assert (m['model'],m['reasoning_effort'],cfg['model'],cfg['model_reasoning_effort'])==('gpt-6-luna','medium','gpt-6-luna','medium')
    assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=CODE,text=True).strip()==m['code_sha']
    assert not subprocess.check_output(['git','status','--porcelain'],cwd=CODE)
    for filename,key in [('home/config.toml','configuration_sha256'),('instructions.md','instructions_sha256'),('prompt.txt','prompt_sha256')]:assert hashlib.sha256((ROOT/filename).read_bytes()).hexdigest()==m[key]
    assert m['limits']==dict(total_turns=3,wall_seconds=1200,tool_calls=80,output_tokens=15000,idle_seconds=180,no_progress_boundaries=2,identical_errors=2,input_telemetry_only=True)
    check_manifest(ROOT/'native-evidence-manifest.json',ROOT/'native-source-packet.txt');return m


def telemetry(budget):
    files=list((ROOT/'home/sessions').rglob('*.jsonl'))
    if len(files)>1:budget.state['stop']='multiple isolated sessions';return
    for file in files:
        for line in file.read_text().splitlines():
            try:row=json.loads(line)
            except ValueError:continue
            typ=row.get('type');p=row.get('payload',{})
            # Inspect only supported model/usage metadata, never session-secret content.
            if typ=='token_usage_record':budget.state['records'][p['response_id']]={'timestamp':row.get('timestamp'),**p}
            if typ=='turn_context':
                model=p.get('model');effort=p.get('effort') or p.get('reasoning_effort')
                if model and model!='gpt-6-luna':budget.state['stop']='effective model mismatch'
                if effort and effort!='medium':budget.state['stop']='effective effort mismatch'
                metadata={'model':model,'effort':effort,'source':'isolated CLI turn_context'}
                (ROOT/'effective-model.json').write_text(json.dumps(metadata,indent=2)+'\n')


def read_status():return get_status(ROOT/'workspace')


def verify(status,traces):
    artifact=finalized_artifact(status,traces)
    if not artifact:return False
    path=artifact.get('path') or artifact.get('bundle_path')
    if not isinstance(path,str):return False
    candidate=Path(path)
    if not candidate.is_absolute():candidate=ROOT/'workspace'/candidate
    candidate=candidate.resolve()
    if not candidate.is_relative_to((ROOT/'workspace').resolve()):return False
    env={**os.environ,'PYTHONPATH':str(CODE/'src')}
    commands=[[PYTHON,'-m','rob2_kit.interfaces.cli.app','verify',str(candidate)],[PYTHON,str(CODE/'scripts/verify_bundle.py'),str(candidate)]]
    results=[]
    for cmd in commands:
        p=subprocess.run(cmd,env=env,capture_output=True,text=True);results.append({'command':cmd,'exit_code':p.returncode,'stdout':p.stdout,'stderr':p.stderr})
    (ROOT/'verifiers.json').write_text(json.dumps({'artifact':artifact,'results':results},indent=2)+'\n');return all(r['exit_code']==0 for r in results)


def run(resume=False):
    manifest=preflight();state_path=ROOT/'budget-state.json'
    if resume:
        assert (ROOT/'delegated-approval.json').exists(),'external sanctioned approval receipt required'
        assert state_path.exists()
    else:assert not state_path.exists(),'No fresh retry allowed'
    b=Budget(json.loads(state_path.read_text()) if state_path.exists() else None);traces=sorted(ROOT.glob('turn-*.jsonl'))
    def save():
        state_path.write_text(json.dumps(b.state,indent=2)+'\n');(ROOT/'usage.json').write_text(json.dumps({'usage':b.usage(),'elapsed_seconds':1200-b.remaining(),'turns':b.state['turns'],'tool_calls':len(b.state['calls']),'stop':b.state['stop'],'output_overshoot':max(0,b.usage()['output_tokens']-15000),'tool_overshoot':max(0,len(b.state['calls'])-80),'reactive_guards':True,'input_telemetry_only':True},indent=2)+'\n')
    def invoke(session,prompt,remaining,index):
        b.begin_turn();n=b.state['turns'];trace=ROOT/f'turn-{n}.jsonl';traces.append(trace);before=read_status();save()
        flags=['--strict-config','--ignore-rules','--skip-git-repo-check','-m','gpt-6-luna','-c','model_reasoning_effort="medium"','-c','features.code_mode={enabled=true,direct_only_tool_namespaces=["mcp__rob2"]}','--json','-o',str(ROOT/f'response-{n}.txt')]
        command=['codex','exec',*flags,'-s','read-only','-'] if session is None else ['codex','exec','resume',*flags,session,'-']
        b.state['events'].append({'event':'launch','turn':n,'session':session,'command':command,'prompt':prompt,'remaining_wall':b.remaining()});save()
        env={**os.environ,'CODEX_HOME':str(ROOT/'home')};buffer=b''
        with trace.open('wb') as log,(ROOT/f'stderr-{n}.log').open('wb') as err:
            p=launch_checked(command,manifest_path=ROOT/'native-evidence-manifest.json',input_path=ROOT/'native-source-packet.txt',receipt_path=ROOT/f'preflight-turn-{n}.json',expected_manifest_sha256=manifest['native_manifest_sha256'],cwd=ROOT/'workspace',env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=err,start_new_session=True)
            p.stdin.write(prompt.encode());p.stdin.close();sel=selectors.DefaultSelector();sel.register(p.stdout,selectors.EVENT_READ);os.set_blocking(p.stdout.fileno(),False)
            def consume(chunk):
                nonlocal buffer
                log.write(chunk);log.flush();buffer+=chunk
                while b'\n' in buffer:
                    line,buffer=buffer.split(b'\n',1)
                    if line.strip():b.consume(json.loads(line))
            try:
                while p.poll() is None:
                    for key,_ in sel.select(0.25):
                        chunk=os.read(key.fileobj.fileno(),65536)
                        if chunk:consume(chunk)
                    telemetry(b);save()
                    if b.check():break
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
                sel.close();telemetry(b);b.boundary(before,read_status());b.check();save()
        return Turn(124 if b.state['stop'] else p.returncode,trace)
    initial=(ROOT/'prompt.txt').read_text()
    continuation='Proposal Review was acknowledged through the researcher CLI under delegated standing authorization. Resume this same assessment/session. Call get_status, recover the approved Result and follow the production workflow through all domains, review, closure and finalize_batch. Scientific judgments remain yours. Stop for an actual blocker or budget.'
    if b.check():result={'boundary':'aborted','reason':b.state['stop']}
    else:
        result=drive(invoke,read_status,lambda s:verify(s,traces),prompt=continuation if resume else initial,session=b.state['session'],max_resumes=2-b.state['turns'] if resume else 0,no_progress_limit=2,wall_seconds=b.remaining())
    b.state['events'].append({'event':'controller_boundary','result':result});save();(ROOT/f'controller-{b.state["turns"]}.json').write_text(json.dumps(result,indent=2)+'\n');(ROOT/'final-status.json').write_text(json.dumps(read_status(),indent=2)+'\n');print(json.dumps({'boundary':result['boundary'],'reason':result['reason'],'turns':b.state['turns'],'usage':b.usage(),'calls':len(b.state['calls'])}))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--resume',action='store_true');parser.add_argument('--preflight-only',action='store_true');args=parser.parse_args()
    if args.preflight_only:preflight();print('Launcher offline preflight passed')
    else:run(args.resume)
