import json,sqlite3,hashlib,csv
from pathlib import Path
from rob2_kit.application.evidence import _evidence_catalog
from rob2_kit.logic import evaluate_domain
root=Path('../diagnostics/frozen-production-9d73225').resolve();out=Path('docs/evaluation/2026-10-02-frozen-production-9d73225');summary=[]
for case,domain in [('an-2021','domain:deviations'),('monarch-plus','domain:missing')]:
 p=out/case;events=[json.loads(line) for line in (p/'events.sanitized.jsonl').read_text().splitlines()];saves=[];actions=[]
 for n,e in enumerate(events):
  i=e.get('item',{})
  if e.get('type')!='item.completed' or i.get('type')!='mcp_tool_call':continue
  actions.append({'event_ordinal':n,'tool':i.get('tool'),'arguments':i.get('arguments'),'status':i.get('status')})
  if i.get('tool')=='save_domain_judgment':saves.append({'event_ordinal':n,'arguments':i['arguments'],'status':i['status'],'result':i.get('result'),'error':i.get('error')})
 (p/'submissions.json').write_text(json.dumps(saves,indent=2)+'\n');(p/'tool-actions.json').write_text(json.dumps(actions,indent=2)+'\n')
 w=root/case/'workspace';db=w/'.rob2-kit/canonical.sqlite3'
 with sqlite3.connect(f'file:{db}?mode=ro',uri=True) as c:state=json.loads(c.execute('select payload from workflow_head').fetchone()[0])
 record=state['domain_records'].get(f'{case}:{domain}');(p/'final-domain-record.json').write_text(json.dumps(record,indent=2)+'\n')
 final=saves[-1]['arguments'];answers={a['question_id']:a['answer'] for a in final['answers']};mapping=evaluate_domain(domain,answers)
 (p/'answer-only-mapping.json').write_text(json.dumps({'evaluation':mapping.model_dump(mode='json'),'production_checkpoint_exists':record is not None,'qualification':'Deterministic mapping of last draft answer enums only. No argument, answer or prose repaired; this does not validate submission structure or scientific warrant and is not counted as an accepted judgment when checkpoint absent.'},indent=2)+'\n')
 handles={b['evidence'] for a in final['answers'] for b in a.get('bases',[])};catalog=_evidence_catalog(w,case);selected={k:v for k,v in catalog.items() if v['handle'] in handles};assert len(selected)==len(handles)
 (p/'selected-evidence.json').write_text(json.dumps(selected,indent=2)+'\n')
 run=json.loads((p/'run.json').read_text());assert run['code_sha']=='9d73225752353916e641910a1f68bb7925a5bddb'
 generation=json.loads((p/'durable-token-usage-records.json').read_text());assert run['usage']['input_tokens']==sum(r['usage']['input_tokens'] for r in generation)
 summary.append({'case':case,'model_owned_checkpoint':record is not None,'server_judgment':record.get('judgment') if record else None,'checkpoint_identity':record.get('identity') if record else None,'rejected_submissions':run['rejected_submissions'],'usage':run['usage'],'uncached_input':run['usage']['input_tokens']-run['usage']['cached_input_tokens'],'elapsed_seconds':run['elapsed_seconds'],'input_overshoot':run['recorded_input_overshoot'],'stop_reason':run['stop_reason']})
(out/'results-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
base=Path('/home/ali/Documents/Code/rob2-kit-benchmark/rob2-meta-set-full-2026-09-29');refs=[]
for name in ['LABELS-batch.csv','OUTCOMES-batch.csv']:
 p=base/name
 with p.open() as f:rows=[r for r in csv.DictReader(f) if r['slug'] in ['an-2021','monarch-plus']]
 refs.append({'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'records':rows,'qualification':'Inspected by operator after runs; withheld from evaluation prompts/tools. Original human labels say (meta outcomes), not an independently verified exact result/cohort/time/analysis scope. No score or adjudication inferred.'})
(out/'human-reference-scope.json').write_text(json.dumps(refs,indent=2)+'\n')
print(json.dumps(summary,indent=2))
