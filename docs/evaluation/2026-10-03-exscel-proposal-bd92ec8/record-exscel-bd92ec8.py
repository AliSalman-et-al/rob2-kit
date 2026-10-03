from pathlib import Path
import json,sqlite3,hashlib,shutil
repo=Path.cwd();root=repo.parent/'diagnostics/frozen-exscel-bd92ec8';out=repo/'docs/evaluation/2026-10-03-exscel-proposal-bd92ec8';out.mkdir(exist_ok=True)
for n in ['manifest.json','prompt.txt','instructions.md','events.jsonl','run.json','durable-token-usage-records.json','preflight.json','native-tools-list.json','native-status-preflight.json','seed-state.json','intake-receipt.json']:
 if (root/n).exists():shutil.copyfile(root/n,out/n)
shutil.copyfile(root/'home/config.toml',out/'cli-config.toml')
for n in ['prepare-exscel-bd92ec8.py','run_exscel_bd92ec8.py','domain_probe_controls_telemetry.py','check-emperor-selection-native.py']:
 shutil.copyfile(root.parent/n,out/n)
shutil.copytree(root/'exported-skill',out/'installed-skill',dirs_exist_ok=True)
with sqlite3.connect(f'file:{root/"workspace/.rob2-kit/canonical.sqlite3"}?mode=ro',uri=True) as c:state=json.loads(c.execute('select payload from workflow_head').fetchone()[0])
(out/'final-state.json').write_text(json.dumps(state,indent=2)+'\n')
events=[json.loads(l) for l in (root/'events.jsonl').read_text().splitlines()];calls=[e['item'] for e in events if e.get('type')=='item.completed' and e.get('item',{}).get('type')=='mcp_tool_call']
(out/'proposal-requests-and-receipts.json').write_text(json.dumps([i for i in calls if i['tool'] in ['validate_proposal','save_proposal']],indent=2)+'\n')
model=[];custom=[]
for p in (root/'home/sessions').rglob('*.jsonl'):
 for l in p.read_text().splitlines():
  r=json.loads(l);v=r.get('payload',{})
  if r['type']=='turn_context':assert (v['model'],v['effort'])==('gpt-6-luna','medium');model.append({k:v.get(k) for k in ['model','effort','turn_id']})
  if r['type']=='response_item' and v.get('type')=='custom_tool_call':custom.append(v)
assert model;(out/'model-settings.json').write_text(json.dumps(model,indent=2)+'\n')
print('STATE',state.keys());print('Saved calls',[(i['tool'],(i.get('result') or {}).get('structured_content',{}).get('outcome')) for i in calls if i['tool'] in ['validate_proposal','save_proposal']]);print('Run',json.loads((root/'run.json').read_text()))
