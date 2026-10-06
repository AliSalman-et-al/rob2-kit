from pathlib import Path
import json,sqlite3,hashlib,shutil,sys
repo=Path.cwd();root=repo.parent/'diagnostics/frozen-award10-d3-fbe8a88';out=repo/'docs/evaluation/2026-10-03-award10-production-d3';out.mkdir(exist_ok=True)
sys.path.insert(0,str(repo.parent/'diagnostics/frozen-award10-fbe8a88-code/src'))
from rob2_kit.application.evidence import main_report_reading_status,source_reading_status
run=json.loads((root/'run.json').read_text());manifest=json.loads((root/'manifest.json').read_text())
for name in ['manifest.json','prompt.txt','instructions.md','observer-criteria.json','events.jsonl','run.json','durable-token-usage-records.json','native-tools-list.json','native-status-preflight.json','launch-preflight.json','response.txt']:
 if (root/name).exists():shutil.copyfile(root/name,out/name)
shutil.copyfile(root/'home/config.toml',out/'cli-config.toml')
for name in ['prepare-award10-d3.py','run_award10_d3.py','check-dapa-native-schema.py','domain_probe_controls_telemetry.py','record-award10-d3.py']:shutil.copyfile(root.parent/name,out/name)
actions=[]
for ordinal,line in enumerate((root/'events.jsonl').read_text().splitlines()):
 e=json.loads(line);i=e.get('item',{})
 if e['type']=='item.completed' and i.get('type')=='mcp_tool_call':actions.append({'event_ordinal':ordinal,**i})
(out/'exact-submissions-and-receipts.json').write_text(json.dumps([a for a in actions if a['tool']=='save_domain_judgment'],indent=2)+'\n')
(out/'selected-evidence.json').write_text(json.dumps([a for a in actions if a['tool'] in ['select_text_evidence','select_visual_evidence']],indent=2)+'\n')
with sqlite3.connect(f'file:{root}/workspace/.rob2-kit/canonical.sqlite3?mode=ro',uri=True) as c:state=json.loads(c.execute('select payload from workflow_head').fetchone()[0])
record=state['domain_records'].get('award-10-2018:domain:missing');(out/'committed-domain.json').write_text(json.dumps(record,indent=2)+'\n')
reading={'main_report':main_report_reading_status(root/'workspace',state['batch']['trials'],phase='assessment'),'sources':source_reading_status(root/'workspace','award-10-2018')};(out/'source-reading-coverage.json').write_text(json.dumps(reading,indent=2)+'\n')
with sqlite3.connect(f'file:{root}/workspace/.rob2-kit/derivative.sqlite3?mode=ro',uri=True) as c:
 receipts=[dict(zip(['source_id','page','start_line','end_line','phase'],row)) for row in c.execute('select source_id,page,start_line,end_line,phase from page_reads order by source_id,page,start_line')]
(out/'source-delivery-receipts.json').write_text(json.dumps(receipts,indent=2)+'\n')
models=[]
for p in (root/'home/sessions').rglob('*.jsonl'):
 for line in p.read_text().splitlines():
  row=json.loads(line);payload=row.get('payload',{})
  if row['type']=='turn_context':
   assert payload['model']=='gpt-6-luna' and payload['effort']=='medium';models.append({k:payload.get(k) for k in ['model','effort','turn_id']})
(out/'model-settings.json').write_text(json.dumps(models,indent=2)+'\n')
original=Path('/home/ali/Documents/Code/rob2-kit-benchmark/benchmark-luna6-medium-2026-10-01/cases/award-10-2018/.rob2-kit')
assert all(hashlib.sha256((original/n).read_bytes()).hexdigest()==h for n,h in manifest['source_database_sha256'].items())
with sqlite3.connect(f'file:{original}/canonical.sqlite3?mode=ro',uri=True) as c:
 old=json.loads(c.execute('select payload from workflow_head').fetchone()[0]);baseline=old['domain_records']['award-10-2018:domain:missing']
(out/'original-accepted-domain.json').write_text(json.dumps(baseline,indent=2)+'\n')
shutil.copyfile(repo/'docs/evaluation/2026-10-02-source-text-post151c385/award-10-2018-response.txt',out/'earlier-source-supplied-response.txt')
print(json.dumps({'run':run,'record':record,'reading':reading},indent=2))
