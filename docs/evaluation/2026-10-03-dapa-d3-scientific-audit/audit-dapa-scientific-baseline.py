from pathlib import Path
import json,sqlite3,csv,hashlib,subprocess,sys,re
import pymupdf
repo=Path.cwd();out=repo/'docs/evaluation/2026-10-03-dapa-d3-scientific-audit';out.mkdir(exist_ok=True)
benchmark=Path('/home/ali/Documents/Code/rob2-kit-benchmark');campaign=benchmark/'benchmark-luna6-medium-2026-10-01';corpus=benchmark/'rob2-meta-set-full-2026-09-29';dev=repo.parent/'diagnostics/cases/dapa-hf';current=repo/'src';baseline=repo.parent/'diagnostics/kit-refined-ad312a4/src'
question={'classification':'Repeated DAPA-HF diagnostic; neither held-out nor generalization evidence.','pinned_before_new_inference':True,'question':'Does production reasoning distinguish actual outcome observation from analysis membership and justify plausible impact of missing outcomes using relevant event counts, reasons/timing and uncertainty?','desired_answers_provided_to_model':False,'new_inference_planned':False,'reason':'Core D3.1 scientific question guidance and missingness-impact instructions are unchanged from the prior baseline. A new stochastic rerun could measure reasoning variation/context presentation, not an implemented impact-warrant improvement.'};(out/'pinned-question.json').write_text(json.dumps(question,indent=2)+'\n')
rows={}
for name in ['OUTCOMES-batch.csv','LABELS-batch.csv']:
 with (corpus/name).open(newline='') as f:rows[name]=next(row for row in csv.DictReader(f) if row['slug']=='dapa-hf')
rows['qualification']='CSV primary-outcome declaration and numerical anchor support endpoint matching. Label metadata omits exact contrast, analysis population, estimand and follow-up; fully aligned remains unknown. Referenced meta-analysis eTable2 raw source is not retained in this benchmark repository.'
(out/'reference-input-rows.json').write_text(json.dumps(rows,indent=2)+'\n')
states={}
for tag,root in [('code_oct1',campaign/'cases/dapa-hf'),('development_oct2',dev)]:
 with sqlite3.connect(f'file:{root}/.rob2-kit/canonical.sqlite3?mode=ro',uri=True) as c:state=json.loads(c.execute('select payload from workflow_head').fetchone()[0])
 record=state['domain_records']['dapa-hf:domain:missing'];states[tag]={'requested_outcome':state['batch']['trials'][0]['requested_outcome'],'result':state['proposal']['payload']['results'][0],'domain':record,'source_state_sha256':hashlib.sha256((root/'.rob2-kit/canonical.sqlite3').read_bytes()).hexdigest(),'scientific_code':('Codecampaignsnapshot' if tag=='code_oct1' else 'ad312a4'),'qualification':'Already observed PY/Low; not a new model outcome.'}
(out/'baseline-results-and-d3.json').write_text(json.dumps(states,indent=2)+'\n')
code='import json;from rob2_kit.packs.scientific import _GUIDANCE;print(json.dumps(_GUIDANCE["sq:missing:data-available"].model_dump(mode="json"),sort_keys=True))'
guidance={}
for tag,path in [('baseline_ad312a4',baseline),('current',current)]:
 result=subprocess.check_output([sys.executable,'-c',code],env={**__import__('os').environ,'PYTHONPATH':str(path)},text=True);guidance[tag]=json.loads(result)
left=json.loads(json.dumps(guidance['baseline_ad312a4']));right=json.loads(json.dumps(guidance['current']))
# Version metadata reflects other question changes, not altered D3.1 scientific text.
left['operational']['version']=right['operational']['version']
assert left==right
old=(baseline/'rob2_kit/skills/rob2-assess/references/missing.md').read_text();new=(current/'rob2_kit/skills/rob2-assess/references/missing.md').read_text()
assert old.replace('"basis_index": 0','"evidence": ["eh_0123456789abcdef"]')==new
comparison={'d31_guidance':guidance,'d31_scientific_text_identical_ignoring_operational_version':True,'missing_reference_change':'Counterevidence handle grammar only; availability/impact scientific prose byte-identical.','other_context_changes':'Material-incompleteness negative proposition and transport/read/context recovery changed; do not supply a stronger affirmative impact warrant for this already-PY branch.','paid_run_not_warranted':True};(out/'guidance-before-current.json').write_text(json.dumps(comparison,indent=2)+'\n')
source=[]
pattern=re.compile(r'incomplete follow.up|unknown vital status|lost to follow.up|withdraw.{0,30}consent|386|502|censor',re.I)
for path in sorted((corpus/'trials/dapa-hf').glob('*.pdf')):
 document=pymupdf.open(path);hits=[]
 for number,page in enumerate(document,1):
  text=page.get_text()
  matches=list(pattern.finditer(text))
  if matches:hits.append({'physical_page':number,'matches':[{'term':m.group(),'context':text[max(0,m.start()-130):m.end()+180]} for m in matches[:8]]})
 source.append({'file':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'pages':len(document),'bounded_keyword_hits':hits,'qualification':'Read-only offline keyword inspection. Absence of a hit is not evidence that a fact is absent; planned censoring/follow-up rules are not observed missingness reasons.'})
 document.close()
(out/'code-source-ledger.json').write_text(json.dumps(source,indent=2)+'\n')
# Contextual binary arithmetic, expressly not an HR robustness/sensitivity analysis.
accounting={'randomized':[2373,2371],'reported_primary_first_events':[386,502],'incomplete_primary_followup':[14,20],'unknown_placebo_vital_status':2,'overlap_unknown':True,'incomplete_over_randomized':[14/2373,20/2371],'incomplete_over_events':[14/386,20/502],'placebo_count_if_unknown_vital_status_disjoint':22,'largest_documented_union_over_placebo_events':22/502,'limitations':'Incomplete follow-up is not necessarily a missing binary value: an earlier first event may already be known. Observed-participant count is not derived by subtraction; person-time, censoring times and outcome-dependence are unknown. Crude event-count arithmetic does not bound the reported hazard ratio or its CI. These calculations contextualize scale only, not a numerical RoB threshold or proof of unbiasedness.'};(out/'missingness-scale-context.json').write_text(json.dumps(accounting,indent=2)+'\n')
for tag,root in [('code_oct1',campaign/'cases/dapa-hf'),('development_oct2',dev)]:
 assert hashlib.sha256((root/'.rob2-kit/canonical.sqlite3').read_bytes()).hexdigest()==states[tag]['source_state_sha256']
assert all(hashlib.sha256((corpus/'trials/dapa-hf'/item['file']).read_bytes()).hexdigest()==item['sha256'] for item in source)
shutil=__import__('shutil');shutil.copyfile(Path(__file__),out/'audit-dapa-scientific-baseline.py')
print(json.dumps({'offline_audit':True,'core_d31_science_unchanged':True,'paid_runs':0,'baseline_py_low_preserved':True,'fully_matched_reference':False,'out':str(out)},indent=2))
