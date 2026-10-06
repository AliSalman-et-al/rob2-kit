from pathlib import Path
import json,sqlite3,hashlib,shutil,sys
repo=Path.cwd();root=repo.parent/'diagnostics/frozen-dapa-d31-warrant-65daa48';out=repo/'docs/evaluation/2026-10-03-d31-impact-warrant';sys.path.insert(0,str(repo.parent/'diagnostics/frozen-d31-warrant-65daa48-code/src'))
from rob2_kit.application.evidence import main_report_reading_status,source_reading_status
run=json.loads((root/'run.json').read_text());manifest=json.loads((root/'manifest.json').read_text());assert run['save_calls']==1 and run['rejections']==0 and run['accepted_checkpoint'] is not None
for name in ['manifest.json','prompt.txt','instructions.md','events.jsonl','run.json','durable-token-usage-records.json','native-tools-list.json','native-status-preflight.json','launch-preflight.json']:
 shutil.copyfile(root/name,out/name)
if (root/'response.txt').exists():shutil.copyfile(root/'response.txt',out/'response.txt')
shutil.copyfile(root/'home/config.toml',out/'cli-config.toml')
for name in ['prepare-dapa-d31-warrant.py','run_dapa_d31_warrant.py','check-dapa-native-schema.py','domain_probe_controls_telemetry.py','record-dapa-d31-warrant.py']:shutil.copyfile(root.parent/name,out/name)
actions=[]
for ordinal,line in enumerate((root/'events.jsonl').read_text().splitlines()):
 e=json.loads(line);i=e.get('item',{})
 if e['type']=='item.completed' and i.get('type')=='mcp_tool_call':actions.append({'event_ordinal':ordinal,**i})
save=next(a for a in actions if a['tool']=='save_domain_judgment');(out/'exact-submission-and-receipt.json').write_text(json.dumps(save,indent=2)+'\n')
selected=[a['result']['structured_content']['data']['evidence'] for a in actions if a['tool']=='select_text_evidence'];(out/'selected-evidence.json').write_text(json.dumps(selected,indent=2)+'\n')
with sqlite3.connect(f'file:{root}/workspace/.rob2-kit/canonical.sqlite3?mode=ro',uri=True) as c:state=json.loads(c.execute('select payload from workflow_head').fetchone()[0])
record=state['domain_records']['dapa-hf:domain:missing'];assert record['judgment']=='low' and record['answers'][0]['answer']=='probably_yes' and len(record['answers'])==1
(out/'committed-domain.json').write_text(json.dumps(record,indent=2)+'\n')
reading={'main_report':main_report_reading_status(root/'workspace',state['batch']['trials'],phase='assessment')['dapa-hf'],'sources':source_reading_status(root/'workspace','dapa-hf'),'qualification':'Tool/derivative receipts establish delivered text coverage, not understanding. Relevant protocol/SAP windows read; do not claim full supplement coverage.'};(out/'source-reading-coverage.json').write_text(json.dumps(reading,indent=2)+'\n')
with sqlite3.connect(f'file:{root}/workspace/.rob2-kit/derivative.sqlite3?mode=ro',uri=True) as c:
 receipts=[dict(zip(['source_id','page','start_line','end_line','phase'],row)) for row in c.execute('select source_id,page,start_line,end_line,phase from page_reads order by source_id,page,start_line')]
(out/'source-delivery-receipts.json').write_text(json.dumps(receipts,indent=2)+'\n')
needle='event counts contextualize scale';proof=[];models=[]
for p in (root/'home/sessions').rglob('*.jsonl'):
 for line in p.read_text().splitlines():
  row=json.loads(line);payload=row.get('payload',{})
  if row['type']=='turn_context':
   assert payload['model']=='gpt-6-luna' and payload['effort']=='medium';models.append({k:payload.get(k) for k in ['model','effort','turn_id']})
  if row['type']=='response_item' and payload.get('type')=='function_call_output' and needle in str(payload.get('output')):
   output=payload['output'];proof.append({'call_id':payload['call_id'],'output_sha256':hashlib.sha256(output.encode()).hexdigest(),'delivered_text_contains_entire_new_warrant': 'Missing reasons or timing alone do not require no_information' in output,'matching_new_instruction':needle,'output':output})
assert proof and all(p['delivered_text_contains_entire_new_warrant'] for p in proof)
(out/'actual-warrant-delivery.json').write_text(json.dumps(proof,indent=2)+'\n');(out/'model-settings.json').write_text(json.dumps(models,indent=2)+'\n')
original=Path('/home/ali/Documents/Code/rob2-kit-benchmark/benchmark-luna6-medium-2026-10-01/cases/dapa-hf/.rob2-kit');assert all(hashlib.sha256((original/n).read_bytes()).hexdigest()==h for n,h in manifest['source_database_sha256'].items())
summary={'scientific_code_sha':run['code_sha'],'classification':'Repeated diagnostic; not held-out/generalization or isolated causal A/B','model':'gpt-6-luna','effort':'medium','paid_invocations':1,'elapsed_seconds':run['elapsed_seconds'],'tools':run['mcp_calls'],'save_attempts':1,'rejections':0,'server_judgment':'low','active_answer':'probably_yes','warrant_improvement_demonstrated':False,'reference_full_scope_match':'unknown','agreement_gain_claimed':False,'accepted_checkpoint':record['identity'],'claim_support':record['evidence_sufficiency'],'criterion_results':{'observation_vs_analysis':'Distinguished explicitly; no invented observed denominator.','event_risk_scale_and_bounds':'No false HR bound, but D3.1 still relies on small fractions and near balance; relevant event-count scale does not enter its affirmative impact warrant.','timing_reasons_unknowns':'Retained; no automatic NI/non-Low solely from missing timing.','explicit_impact_reassurance':'Not established; submitted limitation and committed sufficiency keep impact premise unresolved.'},'planned_vs_performed_sensitivity':'Correctly distinguished planned SAP tipping-point analysis from an executed robustness result. Inactive3.2–3.4 answers were supplied but only3.1 committed; no accepted judgment on inactive questions is claimed.','usage':run['usage'],'uncached_input_tokens':run['uncached_input_tokens'],'input_telemetry_only':True,'output_overshoot':run['output_overshoot'],'tool_overshoot':run['tool_start_overshoot'],'save_overshoot':run['save_start_overshoot'],'main_reading':reading['main_report']['status'],'no_operator_repairs_or_retry':True,'original_code_databases_unchanged':True,'dollars':None,'provider_schema_visibility':'Native declaration verified; hosted request schema not observable. Actual new guidance output delivery verified separately.'}
(out/'scientific-outcome.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2))
