"""Post-freeze reproduction; never used to change or resume this paid run."""
from pathlib import Path
import importlib.util
import pytest
p=Path(__file__).with_name('run_bounded.py');spec=importlib.util.spec_from_file_location('frozen_gupta_runner',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

@pytest.mark.xfail(strict=True,reason='Frozen paid adapter misses completed MCP errors with no structured receipt')
def test_frozen_adapter_stops_repeated_unstructured_validation_errors():
 b=m.Budget(clock=lambda:0)
 row={'type':'item.completed','item':{'type':'mcp_tool_call','tool':'read_pages','status':'completed','result':{'structured_content':None,'content':[{'type':'text','text':'1 validation error for call[read_pages]\npages\nList should have at most 10 items'}]},'error':None}}
 b.consume(row);b.consume(row)
 assert b.check()=='repeated identical error'

def contract_failure(item):
 """Proposed future diagnostic guard: missing typed receipt is a contract failure."""
 result=item.get('result') or {};payload=result.get('structured_content')
 return bool(item.get('error') or item.get('status')=='failed' or not isinstance(payload,dict) or payload.get('outcome') in ['error','condition','repair'])

def test_proposed_classifier_catches_observed_error_shape():
 assert contract_failure({'status':'completed','result':{'structured_content':None,'content':[{'type':'text','text':'34 validation errors for call[save_working_checkpoint]'}]}})
 assert contract_failure({'result':{'structured_content':{'outcome':'repair'}}})
 assert not contract_failure({'result':{'structured_content':{'outcome':'success','data':{'render':{}}}}})
 assert not contract_failure({'result':{'structured_content':{'outcome':'review_required'}}})
