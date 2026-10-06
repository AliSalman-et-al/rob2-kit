import json
from pathlib import Path
from pydantic import BaseModel,ConfigDict,Field
from rob2_kit.models import Answer
from rob2_kit.logic import evaluate_domain
class DraftAnswer(BaseModel):
 model_config=ConfigDict(extra='forbid')
 question_id:str
 answer:Answer
 justification:str=Field(min_length=1)
 source_refs:list[str]
class DraftCase(BaseModel):
 model_config=ConfigDict(extra='forbid')
 id:str
 answers:list[DraftAnswer]
class Draft(BaseModel):
 model_config=ConfigDict(extra='forbid')
 cases:list[DraftCase]
root=Path('docs/evaluation/2026-10-02-d5-guidance-probe');m=json.loads((root/'manifest.json').read_text());items=json.loads((root/'frozen-source-input.json').read_text());out=[]
for version in ('before','after'):
 p=root/version;run=json.loads((p/'run.json').read_text());row={'version':version,'transport_completed':run['exit_code']==0 and run['stop_reason'] is None,'draft_valid':False,'production_checkpoint':False}
 try:
  if not row['transport_completed']:raise ValueError('Invocation incomplete or guard stopped')
  draft=Draft.model_validate_json((p/'response.txt').read_text())
  if [c.id for c in draft.cases]!=[c['id'] for c in items]:raise ValueError('Case membership/order mismatch')
  mapped=[]
  for c in draft.cases:
   if len(c.answers)!=3 or set(a.question_id for a in c.answers)!=set(m['qids']):raise ValueError('Missing or duplicate question')
   mapping={a.question_id:a.answer for a in c.answers}
   e=evaluate_domain('domain:selection',mapping)
   mapped.append({'id':c.id,'answers':{k:v.value for k,v in mapping.items()},'server_computed_mapping':e.model_dump(mode='json')})
  row.update(draft_valid=True,cases=mapped)
 except Exception as exc:row['validation_error']=str(exc)
 out.append(row)
(root/'offline-mapping.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out,indent=2))
