from pathlib import Path
import json,sqlite3,hashlib,shutil,sys
repo=Path.cwd();root=repo.parent/'diagnostics/frozen-emperor-recovery-687fb24';out=repo/'docs/evaluation/2026-10-03-emperor-recovery-687fb24';out.mkdir(exist_ok=True)
sys.path.insert(0,str(repo.parent/'diagnostics/frozen-proposal-687fb24-code/src'))
from rob2_kit.application.evidence import main_report_reading_status
from rob2_kit.workflow_models import ResultProposal
from pydantic import ValidationError
manifest=json.loads((root/'manifest.json').read_text());run=json.loads((root/'run.json').read_text())
assert run['proposal_attempts']==run['proposal_rejections']==2 and run['accepted_proposal_validation'] is None
for name in ['manifest.json','prompt.txt','instructions.md','events.jsonl','run.json','durable-token-usage-records.json','response.txt','preflight.json','native-tools-list.json','native-status-preflight.json','cli-mcp-config-check.json']:
 shutil.copyfile(root/name,out/name)
shutil.copyfile(root/'home/config.toml',out/'cli-config.toml')
for name in ['prepare-emperor-recovery-687fb24.py','run_emperor_proposal_687fb24.py','check-emperor-native-mcp.py','record-emperor-recovery-687fb24.py','domain_probe_controls_telemetry.py']:shutil.copyfile(root.parent/name,out/name)
events=[json.loads(l) for l in (root/'events.jsonl').read_text().splitlines()];actions=[e['item'] for e in events if e['type']=='item.completed' and e.get('item',{}).get('type')=='mcp_tool_call'];attempts=[a for a in actions if a['tool']=='validate_proposal'];(out/'proposal-attempts.json').write_text(json.dumps(attempts,indent=2)+'\n')
errors=[]
for ordinal,attempt in enumerate(attempts,1):
 feedback=json.loads(attempt['result']['content'][0]['text']);all_result_defects=[]
 for index,record in enumerate(attempt['arguments']['results']):
  try:ResultProposal.model_validate(record)
  except ValidationError as exc:all_result_defects.extend({'record_index':index,'path':list(e['loc']),'type':e['type'],'detail':e['msg']} for e in exc.errors(include_input=False,include_url=False))
 errors.append({'attempt':ordinal,'native_feedback_bytes':len(attempt['result']['content'][0]['text'].encode()),'native_feedback':feedback,'unrelated_missing_record_branch_errors':0,'offline_unmodified_result_shape_errors':all_result_defects,'qualification':'Offline model validation explains bounded-away errors; no request repaired, accepted, or saved.'})
(out/'construction-errors.json').write_text(json.dumps(errors,indent=2)+'\n')
selected=[a['result']['structured_content']['data']['evidence'] for a in actions if a['tool']=='select_text_evidence'];(out/'selected-evidence.json').write_text(json.dumps(selected,indent=2)+'\n')
assert any('0.75' in p['quote'] and '0.65 to 0.86' in p['quote'] for p in selected)
with sqlite3.connect(f'file:{root}/workspace/.rob2-kit/canonical.sqlite3?mode=ro',uri=True) as c:state=json.loads(c.execute('select payload from workflow_head').fetchone()[0])
assert all(state.get(k) is None for k in ['proposal','review','proposal_acknowledgment','artifact']) and not state.get('domain_records') and not state.get('reasoning_records')
reading=main_report_reading_status(root/'workspace',state['batch']['trials'],phase='proposal')['emperor-reduced'];(out/'reading-status.json').write_text(json.dumps(reading,indent=2)+'\n')
original=Path('/home/ali/Documents/Code/rob2-kit-benchmark/benchmark-luna6-medium-2026-10-01/cases/emperor-reduced/.rob2-kit');assert all(hashlib.sha256((original/n).read_bytes()).hexdigest()==h for n,h in manifest['source_database_sha256'].items())
model=[]
for p in (root/'home/sessions').rglob('*.jsonl'):
 for line in p.read_text().splitlines():
  row=json.loads(line)
  if row['type']=='turn_context':
   payload=row['payload'];assert payload['model']=='gpt-6-luna' and payload['effort']=='medium';model.append({k:payload.get(k) for k in ['model','effort','turn_id']})
(out/'model-settings.json').write_text(json.dumps(model,indent=2)+'\n')
summary={'code_sha':run['code_sha'],'model':'gpt-6-luna','reasoning_effort':'medium','recovery_invocations':1,'prior_failed_capture_invocation_preserved':True,'elapsed_seconds':run['elapsed_seconds'],'tool_calls':run['mcp_calls'],'proposal_attempts':2,'proposal_validated':False,'proposal_saved':False,'canonical_result_bindings':0,'exit_code':run['exit_code'],'stop_reason':'Model ended voluntarily after two construction failures; no numeric/output/tool/wall/idle/identical guard fired.','usage':run['usage'],'uncached_input_tokens':run['uncached_input_tokens'],'input_limits_enabled':False,'error_reply_bytes':[e['native_feedback_bytes'] for e in errors],'native_mcp_nested_required_collections_verified':True,'hosted_model_service_schema_verified':False,'source_reading_status':reading['status'],'numeric_extraction_correct':True,'claimed_relation':'exact; not validated','scientific_qualification':'Correct HR0.75/CI0.65–0.86 and primary first-event composite recognized; full randomized follow-up distinguished from fixed16-month risk. Article ITT/all-randomized statement supports analysis population, not complete observation. Exact clarity is not supplied; no canonical bindings or validated scope exists.','failure_review':'Attempt1 has invalid estimate/precision/clarity/proof/assessment types. Attempt2 repairs numeric strings/assessment arrays but sends clarity={}, bare handles in advanced evidence, and a missing-facts record in results. Bounded feedback exposes only first eight clarity defects and hides17 further defects; final answer recognizes clarity fields but does not continue. No irrelevant UNION branch errors.','routing_cause':'Previous capture setup replaced default ChatGPT base URL with local HTTP endpoint and disabled transport features; workspace discovery failed before Responses/inference. Restoring default previously working configuration resolves routing. Exact internal discovery rejection was not observable; no auth/security changes or bypasses.','executed':'No-model CLI config/prompt load, native stdio tools/list/get_status, one supported-route directMCP scientific invocation, source reading and evidence selection, two schema-rejected proposals.','unexecuted':'Hosted request capture/visibility, application canonical result source binding, valid scope_review, save/approval, domains, full benchmark.','original_code_benchmark_database_hashes_unchanged':True,'production_code_changes':0,'operator_repairs':0,'accuracy_gain_claimed':False,'billed_dollar_cost':None}
(out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2))
