import importlib.util,json
from pathlib import Path
import pytest
p=Path(__file__).with_name('run_bounded.py');spec=importlib.util.spec_from_file_location('gupta_runner',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def test_budget_persists_across_approval_and_resume():
 now=[0.];b=m.Budget(clock=lambda:now[0]);b.begin_turn()
 b.consume({'type':'thread.started','thread_id':'same'})
 for i in range(40):b.consume({'type':'item.started','item':{'id':str(i),'type':'mcp_tool_call'}})
 b.state['records']['r1']={'usage':{'output_tokens':7000,'reasoning_output_tokens':5000,'input_tokens':9000000}}
 state=json.loads(json.dumps(b.state));now[0]=120;b=m.Budget(state,clock=lambda:now[0]);b.begin_turn()
 assert b.state['turns']==2 and len(b.state['calls'])==40 and b.usage()['output_tokens']==7000 and b.remaining()==1080
 for i in range(40):b.consume({'type':'item.started','item':{'id':str(i),'type':'mcp_tool_call'}})
 assert b.check()=='cumulative tool limit'

def test_output_and_input_telemetry():
 b=m.Budget(clock=lambda:0);b.state['records']['r']={'usage':{'input_tokens':100000000,'output_tokens':14999,'reasoning_output_tokens':12000}}
 assert b.check() is None
 b.state['records']['r']['usage']['output_tokens']=15000
 assert b.check()=='cumulative output limit'

def test_total_turns_bound():
 b=m.Budget(clock=lambda:0)
 for _ in range(3):b.begin_turn()
 with pytest.raises(RuntimeError,match='three-turn'):b.begin_turn()

def test_no_progress_survives_serialization():
 b=m.Budget(clock=lambda:0);b.boundary({'phase':'proposal'},{'phase':'proposal'})
 b=m.Budget(json.loads(json.dumps(b.state)),clock=lambda:0);b.boundary({'phase':'proposal'},{'phase':'proposal'})
 assert b.check()=='two consecutive no-progress boundaries'

def test_error_identity_survives_revision_changes():
 b=m.Budget(clock=lambda:0)
 for rev in [1,2]:
  b.consume({'type':'item.completed','item':{'type':'mcp_tool_call','tool':'x','result':{'structured_content':{'outcome':'repair','head':{'state_revision':rev},'errors':['same']}}}})
 assert b.check()=='repeated identical error'

def test_wall_idle_and_session():
 t=[0];b=m.Budget(clock=lambda:t[0]);t[0]=180;assert b.check()=='idle limit'
 b=m.Budget(clock=lambda:t[0]);t[0]=1400;assert b.check()=='cumulative wall limit'
 b=m.Budget(clock=lambda:0);b.consume({'type':'thread.started','thread_id':'a'});b.consume({'type':'thread.started','thread_id':'b'});assert b.check()=='session changed'

def test_proposal_acknowledgment_not_in_controller():
 source=p.read_text();assert 'approve_review' not in source and "'review'," not in source
