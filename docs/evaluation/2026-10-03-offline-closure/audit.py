import json,sqlite3
from pathlib import Path
repo=Path.cwd(); out=repo/'docs/evaluation/2026-10-03-offline-closure';out.mkdir(exist_ok=True)
benchmark=Path('/home/ali/Documents/Code/rob2-kit-benchmark')
corpus=benchmark/'rob2-meta-set-full-2026-09-29/trials';campaign=benchmark/'benchmark-luna6-medium-2026-10-01'
rows=[]
for case in sorted(corpus.iterdir()):
 if not case.is_dir():continue
 logs=list((campaign/'cases'/case.name).glob('turn-*.jsonl'))
 indicators=[]
 for log in logs:
  count=0
  for line in log.open():
   try:e=json.loads(line)
   except ValueError:continue
   item=e.get('item',{})
   if e.get('type')=='turn.completed' or item.get('type') in ('mcp_tool_call','reasoning','agent_message'):count+=1
  if count:indicators.append({'path':str(log.relative_to(benchmark)),'inference_event_count':count})
 rows.append({'case':case.name,'inference_event_logs':indicators,'campaign_exposure_observed':bool(indicators)})
(out/'exposure-inventory.json').write_text(json.dumps({'scope':'Required Code corpus and preserved October 1 campaign case turn logs. Inference-event presence establishes exposure; absence would require additional archive review, not prove never paid.','cases':rows,'unexposed_candidates':[r['case'] for r in rows if not r['campaign_exposure_observed']]},indent=2)+'\n')
art=repo/'docs/evaluation/2026-10-03-emperor-final-8198144'
src=json.loads((art/'operator-only-continuation-audit.json').read_text())['source']
db=repo.parent/'diagnostics/frozen-emperor-final-8198144/workspace/.rob2-kit/derivative.sqlite3'
con=sqlite3.connect(f'file:{db}?mode=ro',uri=True)
texts={p:t for p,t in con.execute('select page,text from pages where source_id=? and page in (21,22)',(src['id'],))};con.close()
audit={'source':src,'pages':{str(p):[{'line':i,'text':line} for i,line in enumerate(t.splitlines(),1)] for p,t in texts.items()},'delivered_calls':[]}
for line in (art/'events.jsonl').open():
 e=json.loads(line);item=e.get('item',{})
 if e.get('type')=='item.completed' and item.get('tool') in ('read_pages','search_sources_batch','list_sources'):
  audit['delivered_calls'].append(item)
(out/'continuation-delivery-audit.json').write_text(json.dumps(audit,indent=2)+'\n')
print('cases',len(rows),'exposed',sum(r['campaign_exposure_observed'] for r in rows),'candidates',[r['case'] for r in rows if not r['campaign_exposure_observed']])
for p,t in texts.items():
 print('PAGE',p)
 for i,line in enumerate(t.splitlines(),1):
  if p==21 and (i<6 or i>46) or p==22 and i<25:print(i,line)
for item in audit['delivered_calls']:
 if item['tool']=='read_pages' and item['arguments'].get('pages')==[21]:
  data=item['result']['structured_content']['data'];print('page21 response keys',data.keys());print({k:v for k,v in data.items() if k!='pages'})
