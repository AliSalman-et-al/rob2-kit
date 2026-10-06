from pathlib import Path
import json,tempfile
from exscel_recovery_monitor import Monitor
with tempfile.TemporaryDirectory() as d:
 p=Path(d)/'session.jsonl'
 def row(id,out):return {'type':'token_usage_record','payload':{'response_id':id,'usage':{'input_tokens':100,'cached_input_tokens':80,'output_tokens':out}}}
 p.write_text(json.dumps(row('old',5000))+'\n');now=[0.0];m=Monitor(p,clock=lambda:now[0]);assert m.usage()['output_tokens']==0
 p.write_text(p.read_text()+json.dumps(row('turn1',7000))+'\n');assert m.usage()['output_tokens']==7000
 p.write_text(p.read_text()+json.dumps(row('turn2',5000))+'\n');assert m.check()=='cumulative output limit';assert m.summary()['usage']['input_tokens']==200
 p.write_text(json.dumps(row('old',5000))+'\n');m=Monitor(p,clock=lambda:now[0])
 for n in range(60):m.consume({'type':'item.started','item':{'type':'mcp_tool_call','id':str(n)}})
 assert m.check()=='cumulative tool limit'
 m=Monitor(p,clock=lambda:now[0]);m.turn_index=1
 for n in range(30):m.consume({'type':'item.started','item':{'type':'mcp_tool_call','id':str(n)}})
 m.turn_index=2
 for n in range(30):m.consume({'type':'item.started','item':{'type':'mcp_tool_call','id':str(n)}})
 assert m.check()=='cumulative tool limit' and len(m.calls)==60
 m=Monitor(p,clock=lambda:now[0]);now[0]=901;assert m.check()=='total wall limit'
 now[0]=0;m=Monitor(p,clock=lambda:now[0]);now[0]=181;assert m.check()=='idle limit'
 now[0]=0;m=Monitor(p,clock=lambda:now[0]);failure={'type':'item.completed','item':{'type':'mcp_tool_call','tool':'read_pages','status':'failed','result':{'content':[{'text':'schema failure'}],'structured_content':None},'error':None}}
 m.consume(failure);assert m.check() is None;m.consume(failure);assert m.check()=='repeated identical error'
 print('Offline cumulative monitor checks passed: baseline exclusion, cross-turn usage/tools, shared wall/idle, native repeated failures')
