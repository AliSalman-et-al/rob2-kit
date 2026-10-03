from pathlib import Path
import json,sqlite3,hashlib,shutil,tempfile,sys
repo=Path.cwd();sys.path.insert(0,str(repo/'src'))
from rob2_kit.application._state import _state,_result
from rob2_kit.application.domains import _host_asserted_sufficiency
from rob2_kit.application.trials import _review_domain_findings
from rob2_kit.interfaces.mcp.contracts import normalize
out=repo/'docs/evaluation/2026-10-03-d3-premise-review';out.mkdir(exist_ok=True)
probe=repo.parent/'diagnostics/frozen-dapa-d31-warrant-65daa48';campaign=Path('/home/ali/Documents/Code/rob2-kit-benchmark/benchmark-luna6-medium-2026-10-01/cases')
records={}
for case,original in [('dapa-hf',probe/'workspace'),('deliver',campaign/'deliver'),('getgoal-duo1-2013',campaign/'getgoal-duo1-2013')]:
 before=hashlib.sha256((original/'.rob2-kit/canonical.sqlite3').read_bytes()).hexdigest()
 with tempfile.TemporaryDirectory() as temporary:
  copy=Path(temporary)/'workspace';shutil.copytree(original,copy);state=_state(copy)
  record=state['domain_records'][case+':domain:missing'];findings=next(f for f in _review_domain_findings(copy,state,case) if f['domain_id']=='domain:missing')
  records[case]={'original_workspace':str(original),'database_sha256':before,'approved_target':state['proposal']['payload']['results'][0]['target'],'reported_result':state['proposal']['payload']['results'][0]['reported'],'committed_d3':record,'offline_review_projection':findings,'qualification':'Read-only original; projection computed in a disposable copy, not a new assessment or complete trial review approval.'}
  if case=='dapa-hf':
   raw=_result('success',state,checkpoint=record,trial_ready_for_review=False,retry=False)
   save=normalize('save_domain_judgment',raw)['data']['checkpoint']['evidence_sufficiency']
   context=_host_asserted_sufficiency(record['evidence_sufficiency'])
   records[case]['before_attribution']={'save_projection':save,'context_projection':context,'canonical_unchanged':record['evidence_sufficiency'],'note':'Attribution differs solely because save omits context annotation and typed default inserts not_established; unresolved status is unchanged and is not a semantic contradiction verdict.'}
 assert hashlib.sha256((original/'.rob2-kit/canonical.sqlite3').read_bytes()).hexdigest()==before
(out/'actual-case-comparison-and-review.json').write_text(json.dumps(records,indent=2)+'\n')
events=[json.loads(l) for l in (repo/'docs/evaluation/2026-10-03-d31-impact-warrant/events.jsonl').read_text().splitlines()]
contexts=[]
for ordinal,event in enumerate(events):
 item=event.get('item',{})
 if event['type']=='item.completed' and item.get('tool')=='get_domain_context':
  data=item['result']['structured_content']['data'];contexts.append({'event_ordinal':ordinal,'arguments':item['arguments'],'context_page':data.get('context_page'),'working_checkpoint':data.get('working_checkpoint'),'questions':[{'id':q['id'],'activation_status':q.get('activation_status'),'activation':q.get('activation')} for q in data.get('questions',[])],'completion_rule':data.get('completion_rule'),'comparison_propositions':[c.get('propositions') for c in data.get('comparison_cards',[])],'new_guidance_present':'event counts contextualize scale' in json.dumps(data)})
(out/'exact-context-and-premise-state.json').write_text(json.dumps(contexts,indent=2)+'\n')
shutil.copyfile(Path(__file__),out/'audit-dapa-premise-review.py')
print(json.dumps({case:{'answer':r['committed_d3']['answers'][0]['answer'],'label':r['committed_d3']['judgment'],'review_has_warrant':bool(r['offline_review_projection']['answers'][0]['warrant']),'review_limitation_count':len(r['offline_review_projection']['answers'][0]['limitations']),'premise_records':len(r['offline_review_projection']['premise_records'])} for case,r in records.items()},indent=2))
