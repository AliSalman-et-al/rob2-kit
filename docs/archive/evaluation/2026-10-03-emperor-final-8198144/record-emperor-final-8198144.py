from pathlib import Path
import json,sqlite3,hashlib,shutil,sys
repo=Path.cwd();root=repo.parent/'diagnostics/frozen-emperor-final-8198144';out=repo/'docs/evaluation/2026-10-03-emperor-final-8198144';out.mkdir(exist_ok=True)
sys.path.insert(0,str(repo.parent/'diagnostics/frozen-emperor-final-8198144-code/src'))
from rob2_kit.application.evidence import main_report_reading_status
from rob2_kit.application.proposal import _canonical_results,_bind_result
from rob2_kit.application._state import _identity
from rob2_kit.workflow_models import ProposalDraft,ProposalReasoningDraft,AssessableResult
run=json.loads((root/'run.json').read_text());manifest=json.loads((root/'manifest.json').read_text());assert run['proposal_attempts']==3 and run['accepted_proposal_validation']['outcome']=='success'
for name in ['manifest.json','prompt.txt','instructions.md','events.jsonl','run.json','durable-token-usage-records.json','preflight.json','native-tools-list.json','native-status-preflight.json','skill-snapshot.json','observer-criteria.json','seed-state.json']:
 shutil.copyfile(root/name,out/name)
shutil.copyfile(root/'home/config.toml',out/'cli-config.toml');shutil.copytree(root/'exported-skill',out/'installed-skill',dirs_exist_ok=True)
for name in ['prepare-emperor-final-8198144.py','run_emperor_final_8198144.py','check-emperor-selection-native.py','domain_probe_controls_telemetry.py']:shutil.copyfile(root.parent/name,out/name)
es=[json.loads(l) for l in (root/'events.jsonl').read_text().splitlines()];actions=[e['item'] for e in es if e['type']=='item.completed' and e.get('item',{}).get('type')=='mcp_tool_call'];attempts=[a for a in actions if a['tool']=='validate_proposal'];(out/'proposal-attempts.json').write_text(json.dumps(attempts,indent=2)+'\n');accepted=run['accepted_proposal_validation'];(out/'accepted-scope-review.json').write_text(json.dumps(accepted,indent=2)+'\n')
canon=root/'workspace/.rob2-kit/canonical.sqlite3';canon_hash=hashlib.sha256(canon.read_bytes()).hexdigest()
with sqlite3.connect(f'file:{canon}?mode=ro',uri=True) as c:state=json.loads(c.execute('select payload from workflow_head').fetchone()[0])
assert state['phase']=='proposal' and state['proposal'] is None and state['review'] is None and not state.get('domain_records') and len(state['reasoning_records'])==1
record=next(iter(state['reasoning_records'].values()));(out/'validated-reasoning-record.json').write_text(json.dumps(record,indent=2)+'\n');(out/'final-state.json').write_text(json.dumps(state,indent=2)+'\n')
with sqlite3.connect(f'file:{root}/workspace/.rob2-kit/derivative.sqlite3?mode=ro',uri=True) as c:
 c.row_factory=sqlite3.Row;reads=[dict(r) for r in c.execute('select * from page_reads order by source_id,page,start_line')];evidence=[json.loads(r['payload']) for r in c.execute('select payload from evidence_handles')]
 appendix=next(s for s in state['batch']['trials'][0]['sources'] if s['label']=='nejmoa2022190_appendix.pdf')
 continuation=c.execute('select text from pages where source_id=? and page=22',(appendix['id'],)).fetchone()[0]
(out/'read-receipts.json').write_text(json.dumps(reads,indent=2)+'\n');(out/'delivered-evidence.json').write_text(json.dumps(evidence,indent=2)+'\n');sel=set(attempts[-1]['arguments']['selections'][0]['source_passages']);(out/'selected-evidence.json').write_text(json.dumps([e for e in evidence if e['handle'] in sel],indent=2)+'\n')
# Pure reconstruction of the accepted draft: no mutation, revised revision,
# operator-authored fields, additional live validation, or repaired model request.
parsed=ProposalReasoningDraft.model_validate(record['draft']);draft=ProposalDraft(results=parsed.results,expected_revision=parsed.expected_revision);catalog={e['identity']:e for e in evidence};requested={t['id']:t['requested_outcome'] for t in state['batch']['trials']};results,defects,_=_canonical_results(draft,catalog,requested,state['batch']);assert results and not defects
for index,result in enumerate(results):
 ds,_=_bind_result(result,catalog,index,f'/results/{index}',[],sel);assert not ds,ds
result=AssessableResult.model_validate(results[0]).model_dump(mode='json');assert _identity(result)==accepted['data']['scope_review'][0]['result_identity']
(out/'read-only-reconstructed-validated-result.json').write_text(json.dumps({'operator_repair':False,'live_state_mutation':False,'same_result_identity':True,'result':result},indent=2)+'\n')
bindings=[{'path':b['field']['path'],'value_digest':b['value_digest'],'evidence':result['evidence'][b['evidence_index']]} for b in result['bindings']];(out/'source-bindings-audit.json').write_text(json.dumps(bindings,indent=2)+'\n')
assert len(bindings)==4;assert hashlib.sha256(canon.read_bytes()).hexdigest()==canon_hash
(out/'operator-only-continuation-audit.json').write_text(json.dumps({'given_to_model':False,'model_read_this_page':any(r['source_id']==appendix['id'] and r['page']==22 for r in reads),'source':appendix,'page':22,'text':continuation,'finding':'Continuation adds treatment-intensification and duration qualifications; concluding paragraph describes physical signs/laboratory results as supportive when available. Model read page21 only and states objective evidence is required. Preserve this source qualification/conflict rather than unqualified measurement clarity.'},indent=2)+'\n')
reading=main_report_reading_status(root/'workspace',state['batch']['trials'],phase='proposal')['emperor-reduced'];(out/'reading-status.json').write_text(json.dumps(reading,indent=2)+'\n');assert reading['status']=='complete'
model=[];custom=[];direct=[]
for p in (root/'home/sessions').rglob('*.jsonl'):
 for l in p.read_text().splitlines():
  row=json.loads(l);pay=row.get('payload',{})
  if row['type']=='turn_context':
   assert (pay['model'],pay['effort'])==('gpt-6-luna','medium');model.append({k:pay.get(k) for k in ['model','effort','turn_id']})
  if row['type']=='response_item' and pay.get('type') in ['custom_tool_call','custom_tool_call_output']:custom.append(pay)
  if row['type']=='response_item' and pay.get('type')=='function_call':direct.append({'name':pay.get('name'),'call_id':pay.get('call_id')})
assert model;assert len(direct)==11;assert len([c for c in custom if c['type']=='custom_tool_call'])==1
(out/'model-settings.json').write_text(json.dumps(model,indent=2)+'\n');(out/'initial-wrapper-failure.json').write_text(json.dumps(custom,indent=2)+'\n')
original=Path('/home/ali/Documents/Code/rob2-kit-benchmark/benchmark-luna6-medium-2026-10-01/cases/emperor-reduced/.rob2-kit');assert all(hashlib.sha256((original/n).read_bytes()).hexdigest()==h for n,h in manifest['source_database_sha256'].items())
summary={'code_sha':run['code_sha'],'model':'gpt-6-luna','reasoning_effort':'medium','invocations':1,'elapsed_seconds':run['elapsed_seconds'],'MCP_calls':11,'failed_exec_wrapper_calls':1,'observed_total_visible_tool_calls':12,'proposal_attempts':3,'proposal_rejections':2,'operational_validation_success':True,'reviewable_scope_receipt':True,'proposal_saved':False,'human_approved':False,'domains_assessed':0,'server_verified_reported_binding_paths':4,'saved_Result_records':0,'pure_reconstruction_matches_receipt_identity':True,'claimed_relation':'exact','scientific_scope_assessment':'Primary endpoint/first-event window/assignment contrast/all-randomized population/HR and interval correspondence supported. Complete measurement-definition exactness is qualified: model read only first page of a two-page event definition and overstates mandatory objective evidence versus continuation qualifications. Do not equate operational success with unqualified scientific exactness.','source_reading':'Complete12-page main article; appendix page21 only; appendix22 inspected by operator afterward, not given to model or inserted into draft.','usage':run['usage'],'uncached_input_tokens':run['uncached_input_tokens'],'stop_reason':run['stop_reason'],'guard_overshoot_observed':False,'operator_repairs':0,'followup_invocations_authorized_or_performed':0,'same_case_cycle_closed':True,'prior_run_still_protocol_confounded':True,'original_Code_databases_unchanged':True,'accuracy_gain_claimed':False,'causal_gain_claimed':False,'response_file_absent':'Runner stopped on valid reviewable receipt before model final response; all actual attempts and receipt preserved.','CI':'Existing logs only:1f0098e baseline28fail1277pass8skip; all known failures addressed/tested at8198144. No post-fix full-CI outcome asserted or awaited.','billed_dollar_cost':None}
(out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');shutil.copyfile(Path(__file__),out/'record-emperor-final-8198144.py');print(json.dumps(summary,indent=2))
