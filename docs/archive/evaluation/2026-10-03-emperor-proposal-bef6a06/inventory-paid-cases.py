from pathlib import Path
import json
root=Path('/home/ali/Documents/Codex/2026-10-02')
known={'albert-2013','deliver','an-2021','monarch-plus','award-10-2018','getgoal-duo1-2013','canvas-program','dapa-hf'}
records=[]
for p in root.rglob('run.json'):
 if '/.git/' in str(p) or '/.venv/' in str(p):continue
 try:run=json.loads(p.read_text())
 except (OSError,ValueError):continue
 manifest=p.with_name('manifest.json')
 cases=set()
 if manifest.exists():
  m=json.loads(manifest.read_text());c=m.get('case')
  if isinstance(c,str):cases.add(c)
  for c in m.get('cases',[]):
   if isinstance(c,str):cases.add(c)
 if not cases and p.parent.name in known:cases.add(p.parent.name)
 events=p.with_name('events.jsonl')
 if events.exists():
  for line in events.read_text().splitlines():
   try:r=json.loads(line)
   except ValueError:continue
   a=r.get('item',{}).get('arguments',{})
   if isinstance(a,dict):
    if isinstance(a.get('trial_id'),str):cases.add(a['trial_id'])
    for req in a.get('requests',[]):
     if isinstance(req,dict) and isinstance(req.get('trial_id'),str):cases.add(req['trial_id'])
 if cases:
  known.update(cases);records.append({'run':str(p),'cases':sorted(cases),'stop_reason':run.get('stop_reason'),'model':run.get('model')})
# Include original two-case development transcripts, despite missing single-run manifests.
for case in ['albert-2013','dapa-hf']:
 for p in root.rglob(f'cases/{case}/turn-*.jsonl'):
  if '/diagnostics/' in str(p):records.append({'development_turn_log':str(p),'case':case,'qualification':'Parent confirms original same-day development use; original Oct1 baseline participation alone is not exclusion.'})
report={'date':'2026-10-02','explicit_parent_exclusions':['albert-2013','deliver','an-2021','monarch-plus','award-10-2018','getgoal-duo1-2013','canvas-program','dapa-hf'],'excluded_development_cases':sorted(known),'records':records,'scope':'All retained run.json under date workspaces plus parent-provided original development history. Duplicated copied reports are evidence, not unique invocation counts. Original Code Oct1 baseline is not used to exclude additional cases.'}
Path('/home/ali/Documents/Codex/2026-10-02/task-4/diagnostics/paid-case-inventory.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'excluded':sorted(known),'records':len(records)},indent=2))
