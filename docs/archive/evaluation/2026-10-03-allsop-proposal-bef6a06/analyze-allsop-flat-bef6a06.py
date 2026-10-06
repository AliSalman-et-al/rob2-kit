from pathlib import Path
import hashlib,json,sqlite3,shutil,sys
repo=Path('/home/ali/Documents/Codex/2026-10-02/task-4/rob2-kit');sys.path.insert(0,str(repo/'src'))
from rob2_kit.application.evidence import source_reading_status,main_report_reading_status
root=repo.parent/'diagnostics/frozen-allsop-flat-bef6a06';out=repo/'docs/evaluation/2026-10-03-allsop-proposal-bef6a06';out.mkdir(exist_ok=True)
manifest=json.loads((root/'manifest.json').read_text());run=json.loads((root/'run.json').read_text());records=json.loads((root/'durable-token-usage-records.json').read_text())
assert manifest['code_sha']==run['code_sha']=='bef6a06c133432ed3c45787bbaed4ebf5c6ae36a'
assert run['proposal_attempts']==run['proposal_attempts_completed']==4 and run['proposal_rejections']==4
assert run['stop_reason']=='proposal construction allowance exhausted' and run['input_limits_enabled'] is False
assert run['accepted_proposal_validation'] is None
for name in ['manifest.json','prompt.txt','instructions.md','events.jsonl','run.json','durable-token-usage-records.json','frozen-mcp-tools.json','preflight.json']:shutil.copyfile(root/name,out/name)
shutil.copyfile(root/'home/config.toml',out/'cli-config.toml')
for name in ['prepare-allsop-flat-bef6a06.py','run_scope_case_b12fe45.py','domain_probe_controls_telemetry.py','analyze-allsop-flat-bef6a06.py']:shutil.copyfile(repo.parent/'diagnostics'/name,out/name)
events=[json.loads(l) for l in (root/'events.jsonl').read_text().splitlines()]
actions=[{'event_ordinal':n,**e['item']} for n,e in enumerate(events) if e['type']=='item.completed' and e.get('item',{}).get('type')=='mcp_tool_call']
attempts=[i for i in actions if i['tool']=='validate_proposal'];(out/'proposal-attempts.json').write_text(json.dumps(attempts,indent=2)+'\n')
with sqlite3.connect(f'file:{root}/workspace/.rob2-kit/canonical.sqlite3?mode=ro',uri=True) as c:state=json.loads(c.execute('select payload from workflow_head').fetchone()[0])
assert all(state[k] is None for k in ['proposal','review','proposal_acknowledgment','artifact']) and not state['domain_records'] and not state['reasoning_records']
selected=[{'event_ordinal':i['event_ordinal'],**i['result']['structured_content']['data']['evidence']} for i in actions if i['tool']=='select_text_evidence'];(out/'selected-evidence.json').write_text(json.dumps(selected,indent=2)+'\n')
reads=[];quotes=[];native_scope=[]
for item in actions:
 result=(item.get('result')or{}).get('structured_content')or{};data=result.get('data',{})
 if 'scope_review' in data:native_scope.append({'event_ordinal':item['event_ordinal'],'tool':item['tool'],'scope_review':data['scope_review']})
 if item['tool']=='read_pages':
  for page in data.get('pages',[]):
   reads.append({'event_ordinal':item['event_ordinal'],**{k:v for k,v in page.items() if k!='numbered_text'}})
   for start,end,label in ({7:[(34,58,'Table2 endpoint/headers/quantities'),(156,160,'Table2 window footnotes')],4:[(14,35,'ITT/model methods'),(75,81,'Unadjusted and adjusted statistics')],8:[(154,164,'Table3 window/covariate footnotes')]}.get(page['page'],[])):
    text='\n'.join(l for l in page['numbered_text'].splitlines() if start<=int(l.split('|')[0])<=end)
    if text:quotes.append({'event_ordinal':item['event_ordinal'],'source_id':page['source_id'],'page':page['page'],'label':label,'requested_start_line':start,'requested_end_line':end,'numbered_text':text,'read_passage_ref':page.get('passage_ref')})
with sqlite3.connect(f'file:{root}/workspace/.rob2-kit/derivative.sqlite3?mode=ro',uri=True) as c:receipts=[dict(zip(['source_id','page','start_line','end_line','phase'],r)) for r in c.execute('select source_id,page,start_line,end_line,phase from page_reads order by page,start_line')]
assert any(r['page']==11 and r['start_line']==2 and r['end_line']==186 for r in receipts)
coverage={'native_read_page_windows':reads,'durable_page_read_receipts':receipts,'source_reading_status':source_reading_status(root/'workspace','allsop-2014'),'main_report_reading':main_report_reading_status(root/'workspace',state['batch']['trials'],phase='proposal')['allsop-2014'],'qualification':'Receipt fix works in this paid run: page11 lines2–186 durable. Line1 was delivered in two character fragments and remains unclaimed by line-only receipts. No supplement read. Do not claim full durable source reading or completed bounded main pass.'};(out/'coverage.json').write_text(json.dumps(coverage,indent=2)+'\n');(out/'native-source-quotes.json').write_text(json.dumps(quotes,indent=2)+'\n')
assert any('all days (1-9)' in q['numbered_text'] for q in quotes)
public_scopes=[]
for n,a in enumerate(attempts,1):
 card=a['arguments']['results'][0];assessment=a['arguments']['assessments'][0]
 public_scopes.append({'attempt':n,'claimed_relation':card['relation'],'relation_rationale':card.get('relation_rationale'),'target_window':card.get('target_window'),'reported_result':card.get('reported_result'),'reported_outcome':card.get('reported_outcome'),'reported_definition':card.get('reported_definition'),'analysis_population':card.get('analysis_population'),'effect_measure':card.get('effect_measure'),'estimate':card.get('estimate'),'design_evidence':card.get('design_evidence'),'passage_refs':card.get('passage_refs'),'scope_justification':assessment.get('scope_justification'),'population_justification':assessment.get('population_justification'),'unknowns':assessment['unknowns']})
semantic={'proposed_scopes':public_scopes,'original_target':manifest['original_target'],'source_window_found_and_delivered':True,'temporal_relation_review':'Broader is supported for the model time-window axis (days1–9 versus target1–6). It is not an accepted full-scope judgment: cards combine omnibus test statistics, adjusted/unadjusted analyses and within-group percentage changes rather than one comparative estimate, and do not establish equivalent estimand scope. A related candidate or a supported group-bound candidate requires further source-grounded interpretation; no forced label or retargeting was applied.','first_attempt_recognized_nonexact_scope_in_prose':True,'relations':[a['arguments']['results'][0]['relation'] for a in attempts],'flat_model_proposal_validated':False,'saved':False,'canonical_result_bindings':[],'binding_status':'Unavailable: all four calls failed schema validation before application source-binding/canonicalization. Assessment references are source premises, not validated Result field bindings.','explicitly_selected_evidence_locations':[(v['page'],v['start_line'],v['end_line']) for v in selected],'explicit_assessment_basis_includes_window_footnote':False,'basis_qualification':'The footnote is in a native read response and its read-page passage handle is available. The three explicitly selected handles referenced in assessments cover endpoint definition, result paragraph and Table2 row, not the footnote. No canonical binding was constructed.','scope_review_deliveries':native_scope,'decision_benefit_observed':False,'qualification':'Known-case test, not unseen agreement or accuracy. Recognition in prose preceded any populated scope review. Invalid supports was replaced by explicit broader, but no valid retained proposal or durable decision was produced.'};(out/'scope-outcome.json').write_text(json.dumps(semantic,indent=2)+'\n')
usage={key:sum(r['usage'].get(key,0) for r in records) for key in run['usage']};assert usage==run['usage'];assert usage['input_tokens']-usage['cached_input_tokens']==run['uncached_input_tokens']
orig=Path('/home/ali/Documents/Code/rob2-kit-benchmark/benchmark-luna6-medium-2026-10-01/cases/allsop-2014/.rob2-kit');assert all(hashlib.sha256((orig/n).read_bytes()).hexdigest()==h for n,h in manifest['source_database_sha256'].items())
model_records=[]
for p in (root/'home/sessions').rglob('*.jsonl'):
 for line in p.read_text().splitlines():
  row=json.loads(line)
  if row['type']=='turn_context':
   payload=row['payload'];assert payload['model']=='gpt-6-luna' and payload['effort']=='medium';model_records.append({k:payload.get(k) for k in ['model','effort','turn_id','root_turn_id','approval_policy','sandbox_policy']})
(out/'model-settings.json').write_text(json.dumps(model_records,indent=2)+'\n')
summary={'code_sha':run['code_sha'],'model':'gpt-6-luna','reasoning_effort':'medium','paid_invocations':1,'elapsed_seconds':run['elapsed_seconds'],'mcp_calls':run['mcp_calls'],'mcp_calls_completed':run['mcp_calls_completed'],'proposal_attempts':4,'schema_rejections':4,'usage':usage,'uncached_input_tokens':run['uncached_input_tokens'],'input_limits_enabled':False,'stop_reason':run['stop_reason'],'exit_code':run['exit_code'],'proposal_validated':False,'proposal_saved':False,'populated_scope_review_delivered':False,'decision_benefit_observed':False,'native_page11_receipt_recovery_verified':True,'source_database_hashes_unchanged':True,'no_retry':True,'manual_repairs':0,'production_code_changes_during_run':0,'new_fields_added_after_run':0,'dollar_cost':None,'cost_qualification':'Durable token totals are actual usage telemetry. This ChatGPT-authenticated CLI run supplies no billed-dollar amount or verified per-token rate; no guessed API dollar estimate.','schema_visibility_qualification':'Captured exact FastMCP advertised flat schema and same frozen CLI MCP configuration. Native errors confirm the replacement models enforced. Provider request/tool-declaration payload is not present in the rollout; no claim that the complete schema was independently observed at the model service boundary.'};(out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2))
