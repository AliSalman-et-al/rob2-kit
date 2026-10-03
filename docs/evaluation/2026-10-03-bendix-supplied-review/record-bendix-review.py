from pathlib import Path
import json,hashlib,shutil
repo=Path.cwd();root=repo.parent/'diagnostics/frozen-bendix-review-9d28651';out=repo/'docs/evaluation/2026-10-03-bendix-supplied-review';out.mkdir(exist_ok=True)
for name in ['manifest.json','observer-criteria.json','frozen-review-materials.json','prompt.txt','instructions.md','response.txt','events.jsonl','run.json','durable-token-usage-records.json']:shutil.copyfile(root/name,out/name)
for name in ['prepare-bendix-review.py','run-bendix-review.py','record-bendix-review.py']:shutil.copyfile(root.parent/name,out/name)
shutil.copyfile(root/'home/config.toml',out/'cli-config.toml')
run=json.load(open(root/'run.json'));assert run['durable_response_generations']==1 and run['final_messages']==1 and run['tool_calls']==0
manifest=json.load(open(root/'manifest.json'));assert hashlib.sha256((root/'prompt.txt').read_bytes()).hexdigest()==manifest['prompt_sha256'];assert hashlib.sha256((root/'frozen-review-materials.json').read_bytes()).hexdigest()==manifest['materials_sha256']
models=[];texts=[]
for p in (root/'home/sessions').rglob('*.jsonl'):
 for line in p.read_text().splitlines():
  row=json.loads(line);q=row.get('payload',{})
  if row['type']=='turn_context':
   assert q['model']=='gpt-6-luna' and q['effort']=='medium';models.append({k:q.get(k) for k in ['model','effort','turn_id']})
  if row['type']=='response_item' and q.get('type')=='message' and q.get('role')=='assistant':
   for content in q.get('content',[]):
    if content.get('type')=='output_text':texts.append(content['text'])
response=(root/'response.txt').read_text().strip();assert texts and texts[-1].strip()==response
(out/'response-proof.json').write_text(json.dumps({'model_settings':models,'actual_response_generations':1,'tool_calls':0,'exact_final_text_matches_durable_assistant_text':True,'response_sha256':hashlib.sha256(response.encode()).hexdigest(),'prompt_sha256':manifest['prompt_sha256'],'no_retry_or_repair':True},indent=2)+'\n')
(out/'scientific-outcome.json').write_text(json.dumps({'review_calibration_criterion':'not met','reason':'Retains definitive No and categorical not-merely-missing assertion without comparing supported missing-only versus completion-conditioned interpretations; unknown outcomes retained.','D2_3':'NI retained with correct ordinary-care/trial-context distinction','D2_7':'PY retains uncertain potential impact but nine exclusions still treated as established D2 population','High_wrong_claimed':False,'full_workflow_failure_claimed':False,'product_changed':False,'next_hypothesis':'Draft anchoring versus persistent source-to-exclusion reasoning; one future source-only independent appraisal of same evidence/guidance could discriminate, with task-change confounding acknowledged.'},indent=2)+'\n')
print({k:run[k] for k in ['elapsed_seconds','usage','uncached_input_tokens','response_word_count','output_overshoot']})
