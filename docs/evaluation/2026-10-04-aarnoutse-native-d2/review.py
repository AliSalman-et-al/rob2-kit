"""Offline source/warrant review after frozen output; no inference or repairs."""
from pathlib import Path
import hashlib,json,sqlite3
from rob2_kit.application._state import _canonical_evidence_records,_state
from rob2_kit.logic.evaluator import evaluate_domain
R=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def write(n,x):(R/n).write_text(json.dumps(x,indent=2,ensure_ascii=False)+'\n')
for n,h in json.loads((R/'answer-freeze.json').read_text()).items():assert sha(R/n)==h
m=json.loads((R/'manifest.json').read_text());assert sha(R/'independent-facts.md')==m['independent_facts_sha256'];assert sha(R/'private-criteria.md')==m['private_criteria_sha256']
state=_state(R/'workspace');saved=state['domain_records']['aarnoutse-2017:domain:deviations'];write('saved-d2.json',saved)
original=json.loads((R/'original-result.json').read_text());current=state['proposal']['payload']['results'][0]
for k in ['target','reported','relation']:assert current[k]==original[k]
assert json.loads((R/'effective-model.json').read_text())==[{'model':'gpt-6-luna','effort':'medium'}]
receipts=json.loads((R/'native-receipts.json').read_text());run=json.loads((R/'run.json').read_text())
assert len(receipts)==run['tool_calls']==15
assert len([x for x in receipts if x['tool']=='save_domain_judgment' and x['receipt']['outcome']=='success'])==1
assert len(run['submission_rejections'])==1
assert all(x['arguments'].get('domain_id')=='domain:deviations' for x in receipts if x['tool']=='save_domain_judgment')
assert not any(x['arguments'].get('guidance_profile')=='official_d3_prototype' for x in receipts)
assert not any(x['tool']=='save_working_checkpoint' for x in receipts)
initial_reading=next(x['receipt']['data']['main_report_reading']['aarnoutse-2017'] for x in receipts if x['tool']=='get_status')
final_reading=[x['receipt']['data']['main_report_reading']['aarnoutse-2017'] for x in receipts if x['tool']=='get_status'][-1]
assert final_reading['status']=='complete' and not final_reading['required_ranges']
delivered=json.loads((R/'delivered-source-windows.json').read_text())
for required in initial_reading['required_ranges']:
 spans=sorted((x['start_line'],x['end_line']) for x in delivered if x['source_id']==required['source_id'] and x['page']==required['page'])
 cursor=required['start_line']
 for start,end in spans:
  if start>cursor:break
  cursor=max(cursor,end+1)
 assert cursor>required['end_line'],required
assert len(initial_reading['required_ranges'])==13
assert not json.loads((R/'native-image-identities.json').read_text())
assert not any(b.get('working_observation') for a in saved['answers'] for b in a['bases'])
with sqlite3.connect(f'file:{R}/workspace/.rob2-kit/working.sqlite3?mode=ro',uri=True) as db:assert db.execute('SELECT COUNT(*) FROM working_checkpoints').fetchone()[0]==0
assert saved['active_questions']==[x['question_id'] for x in saved['answers']]
evaluated=evaluate_domain('domain:deviations',{a['question_id']:a['answer'] for a in saved['answers']});assert str(evaluated.judgment)==saved['judgment']=='low'
ids={b['evidence'] for a in saved['answers'] for b in a['bases']};catalog=_canonical_evidence_records(R/'workspace',ids);assert ids==set(catalog)
for a in saved['answers']:
 for b in a['bases']:assert b['source']==catalog[b['evidence']]['quote']
source=json.loads((R/'source-provenance.json').read_text())['new_capture_sources'][0]['id']
source_windows=[]
# Include uncited discriminating passages rather than just replaying saved citations.
windows=[(2,42,56),(3,1,167),(4,14,126),(5,1,155),(6,1,112),(9,38,56),(10,30,66),(11,47,59),(12,1,76)]
with sqlite3.connect(f'file:{R}/workspace/.rob2-kit/derivative.sqlite3?mode=ro',uri=True) as db:
 for page,start,end in windows:
  body=db.execute('SELECT text FROM pages WHERE source_id=? AND page=?',(source,page)).fetchone()[0]
  lines=body.splitlines();quote='\n'.join(lines[start-1:end]);source_windows.append({'source_id':source,'page':page,'start_line':start,'end_line':end,'quote':quote,'numbered_text':'\n'.join(f'{i}|{line}' for i,line in enumerate(lines,1) if start<=i<=end),'attribution':'independent source review; model delivery recorded separately'})
write('selected-evidence.json',catalog)
findings=[
 {'question_id':'sq:deviations:participants-aware','answer':'probably_no','assessment':'Defensible probabilistic inference from double-blind description and equal capsule numbers including placebo. Actual guessing/symptom cues unknown, correctly qualified. Matching appearance is inferred, not separately proven by the selected passage.','source_coordinates':[{'page':10,'start_line':30,'end_line':51}]},
 {'question_id':'sq:deviations:personnel-aware','answer':'probably_no','assessment':'Defensible qualified inference from double-blind/placebo design; staff roles and actual awareness not explicitly enumerated. Rejected unknown handle was replaced by a valid same-passage context citation; this fixes ownership, not additional proof of blinding.','source_coordinates':[{'page':10,'start_line':30,'end_line':51}]},
 {'question_id':'sq:deviations:appropriate-analysis','answer':'yes','assessment':'Correctly keeps week-six rifampin PK sample23/21/19 distinct from150 randomized and from bacteriological exclusions/censoring. Source describes group-based PK analysis and an intentionally smaller PK sample, so the smaller denominator alone does not make D2 analysis inappropriate. Warrant relies partly on absence of reported observed-data exclusion/reassignment and admits sampling/hospitalization uncertainty; definite Yes is stronger than that argument establishes. A qualified ProbablyYes can be defensible without changing the server Low label; an unresolved selection mechanism could also justify concerns if stronger inference is unwarranted. No preferred answer imposed.','under_discussed':'Main11 lines47–59 specifies PK power around20/arm versus50/arm for safety and log-transformed between-group ANOVA. Main10 sampling counts23/20/20 conflict with Results/Table2 counts23/21/19. The record leaves exact absence reasons unknown but does not explicitly resolve or retain that count conflict. Neither culture exclusions nor later continuation dosing is imported into the PK conclusion.','source_coordinates':[{'page':2,'start_line':42,'end_line':56},{'page':4,'start_line':14,'end_line':126},{'page':10,'start_line':55,'end_line':66},{'page':11,'start_line':47,'end_line':59}]}]
contexts=[{'item':x['item'],'index':x['receipt']['data']['context_page']['index'],'delivery_status':x['receipt']['data']['context_page']['delivery_status'],'next_cursor':x['receipt']['data']['context_page']['next_cursor']} for x in receipts if x['tool']=='get_domain_context']
review={'case':'aarnoutse-2017','implementation_sha':m['implementation_sha'],'model':run['model_context'],'result_target_report_relation_unchanged':True,'original_source_complete_and_hash_verified':True,'working_observation_calls':0,'typed_scopes_saved':0,'warrant_links_saved':0,'feature_benefit_demonstrated':False,'scope_facts_in_prose':['Three dose groups and week-six PK measurement','PK sample23/21/19 versus150 randomized','Hospitalized PK sampling versus broader trial context'],'native_label':'low','label_review':'Algorithmic Low is correct for PN/PN/Yes. Scientifically defensible as a qualified D2 conclusion, not proof of complete analysis-population validity; definite2.6confidence and missingness/substudy explanation are refinable. This is not a matched human accuracy assessment. D3 outcome availability not evaluated.','trial_context_cause':'2.3–2.5 are inactive under PN/PN awareness answers. No affirmative trial-context cause claimed; the case provides no active-path comparison of that reasoning. Protocol-permitted meal changes and continuation-phase uniform doses are not falsely treated as week-six trial-caused deviations.','findings':findings,'answers':saved['answers'],'selected_evidence':catalog,'independent_relevant_source_windows':source_windows,'source_delivery':{'all13pages_read':True,'reading_recovery_completed':True,'native_delivered_windows':20,'model_images':0,'initial_D2_context_complete':True,'later_redundant_context_restart_left_incomplete':True,'contexts':contexts,'note':'First four-page context chain delivered all D2 questions/guidance before targeted investigation. A later redundant restart returned an incomplete header and was not drained before save; prior complete context and read source premises existed. This is a workflow deviation, not demonstrated missing scientific content or a scope-binding defect.'},'rejection_review':{'count':1,'code':'invalid_evidence','path':'/answers/1/bases/1/evidence','rejected_handle':'eh_5291b9c9c6e1de16','repair':'Replaced by valid eh_94834a706ea53341; no scientific answer changed','validator_preserved_grounding':True},'usage':{**run['usage'],'uncached_input_tokens':run['uncached_input_tokens'],'elapsed_seconds':run['elapsed_seconds'],'tool_calls':run['tool_calls'],'provider_responses':run['provider_response_count']},'runtime_defect_supported_by_trace':False,'postrun_runtime_fix':False,'reason_no_more_machinery':'Optional features were exposed and generically documented but not used. Do not force notes/labels or infer an ergonomic cause from nonuse. Source interpretation/confidence and redundant pagination need honest reporting, not case-specific parsing or a preferred-answer gate.','paid_retries':0,'original_output_hashes_unchanged':True,'before_after_observable':'Before22edcd7: scope/link schemas existed but no skill workflow or public tool description; obsolete counterevidence-index instruction. After: native audit confirms coherent generic descriptions and exported reference delivery. Scientific run: ordinary prose facts and accepted judgment, no scope/link use; no causal scientific before/after claim.'}
write('scientific-review.json',review)
print('Offline assertions passed: exact original Result, original sources, LunaMedium, one accepted D2, scoped-feature nonuse, quote/coordinate bindings and canonical Low. No paid call or repaired judgment.')
