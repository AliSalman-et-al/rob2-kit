from pathlib import Path
import json,sqlite3,hashlib,shutil,sys
repo=Path.cwd();root=repo.parent/'diagnostics/frozen-emperor-selection-3fec228';out=repo/'docs/evaluation/2026-10-03-emperor-selection-3fec228';out.mkdir(exist_ok=True)
sys.path.insert(0,str(repo.parent/'diagnostics/frozen-emperor-selection-code/src'))
from rob2_kit.application.evidence import main_report_reading_status
run=json.loads((root/'run.json').read_text());manifest=json.loads((root/'manifest.json').read_text())
assert run['proposal_attempts']==1 and run['accepted_proposal_validation'] is None
for name in ['manifest.json','prompt.txt','instructions.md','events.jsonl','run.json','durable-token-usage-records.json','response.txt','preflight.json','native-tools-list.json','native-status-preflight.json','construction-counts.json','export-consistency.json','skill-snapshot.json','observer-criteria.json','seed-state.json']:
 shutil.copyfile(root/name,out/name)
shutil.copyfile(root/'home/config.toml',out/'cli-config.toml');shutil.copytree(root/'exported-skill',out/'installed-skill',dirs_exist_ok=True)
for name in ['prepare-emperor-selection.py','run_emperor_selection.py','check-emperor-selection-native.py','domain_probe_controls_telemetry.py']:shutil.copyfile(root.parent/name,out/name)
es=[json.loads(l) for l in (root/'events.jsonl').read_text().splitlines()];actions=[e['item'] for e in es if e['type']=='item.completed' and e.get('item',{}).get('type')=='mcp_tool_call'];attempts=[a for a in actions if a['tool']=='validate_proposal'];(out/'proposal-attempts.json').write_text(json.dumps(attempts,indent=2)+'\n')
with sqlite3.connect(f'file:{root}/workspace/.rob2-kit/canonical.sqlite3?mode=ro',uri=True) as c:
 state=json.loads(c.execute('select payload from workflow_head').fetchone()[0]);tables=[r[0] for r in c.execute('select name from sqlite_master where type="table"')]
assert state.get('proposal') is None and not state.get('domain_records') and not state.get('reasoning_records')
(out/'final-state.json').write_text(json.dumps(state,indent=2)+'\n')
with sqlite3.connect(f'file:{root}/workspace/.rob2-kit/derivative.sqlite3?mode=ro',uri=True) as c:
 c.row_factory=sqlite3.Row;reads=[dict(r) for r in c.execute('select * from page_reads order by source_id,page,start_line')];evidence=[json.loads(r['payload']) for r in c.execute('select payload from evidence_handles')]
(out/'read-receipts.json').write_text(json.dumps(reads,indent=2)+'\n');(out/'delivered-evidence.json').write_text(json.dumps(evidence,indent=2)+'\n')
selected=set(attempts[0]['arguments']['selections'][0]['source_passages']);(out/'selected-evidence.json').write_text(json.dumps([e for e in evidence if e['handle'] in selected],indent=2)+'\n')
reading=main_report_reading_status(root/'workspace',state['batch']['trials'],phase='proposal')['emperor-reduced'];(out/'reading-status.json').write_text(json.dumps(reading,indent=2)+'\n')
model=[]
for p in (root/'home/sessions').rglob('*.jsonl'):
 for l in p.read_text().splitlines():
  row=json.loads(l)
  if row['type']=='turn_context':
   t=row['payload'];assert (t['model'],t['effort'])==('gpt-6-luna','medium');model.append({k:t.get(k) for k in ['model','effort','turn_id']})
(out/'model-settings.json').write_text(json.dumps(model,indent=2)+'\n');assert model
original=Path('/home/ali/Documents/Code/rob2-kit-benchmark/benchmark-luna6-medium-2026-10-01/cases/emperor-reduced/.rob2-kit');assert all(hashlib.sha256((original/n).read_bytes()).hexdigest()==h for n,h in manifest['source_database_sha256'].items())
summary={'code_sha':run['code_sha'],'exact_model':'gpt-6-luna','reasoning_effort':'medium','invocations':1,'elapsed_seconds':run['elapsed_seconds'],'tool_calls':run['mcp_calls'],'proposal_attempts':1,'schema_accepted':True,'scientific_validation_accepted':False,'proposal_saved':False,'researcher_approval':False,'scope_review_produced':False,'canonical_numerical_bindings':0,'scientific_repairs':['incoherent_reported_result','result_value_not_supported'],'claimed_relation':'narrower','reading_status':reading['status'],'usage':run['usage'],'uncached_input_tokens':run['uncached_input_tokens'],'stop':'Model ended voluntarily after one application repair. No guard fired. Response explicitly construed no retry/manual repair as stopping after one attempt.','prompt_limitation':'Prompt also explicitly allowed four validation attempts, but no retry phrasing ambiguously suggested no in-invocation correction. This is an operator prompt confound; no second invocation or repaired draft.','schema_behavior':'One actual selections object with candidate, source_passages, typed clarity and reasoning reached application validators without schema construction defects. Current contract was used, not merely delivered.','scientific_audit':'Correct primary HR and numerical CI limits recognized. Endpoint exact wording and precision literal binding failed. Eligibility-based narrower scope not defensible for this stated all-randomized trial target without additional target-population justification. All-randomized ITT correctly separated from incomplete follow-up.','comparison_limits':'Prior recovery had 7/25 schema defects; this one reaches scientific repair. Same case but changed tool allowance20→25 and installed skill/prompt delivery; cannot attribute causality, lower usage, validated scope or RoB accuracy gain.','operator_repairs':0,'original_code_databases_unchanged':True,'full_benchmark':False,'accuracy_gain_claimed':False,'known_CI':'Prior inspected job44failures; relevant current release/fixture fixes and focused checks passed, unrelated broad failures remain. Current checkpoint CI was only observed in_progress; no wait.','billed_dollar_cost':None}
(out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');shutil.copyfile(Path(__file__),out/'record-emperor-selection.py');print(json.dumps(summary,indent=2))
