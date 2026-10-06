"""Frozen native transfer review; no model calls or repaired assessment."""
from pathlib import Path
import json,hashlib,sqlite3
R=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def write(n,x):(R/n).write_text(json.dumps(x,indent=2,ensure_ascii=False)+'\n')
for n,h in json.loads((R/'answer-freeze.json').read_text()).items():assert sha(R/n)==h
m=json.loads((R/'manifest.json').read_text());assert sha(R/'independent-facts.md')==m['independent_facts_sha256']
r=json.loads((R/'native-receipts.json').read_text());saved=json.loads((R/'saved-d3.json').read_text());rows=saved['answers'][0]['missing_data']['rows']
assert [(x['randomized'],x['analyzed'],x['completed']) for x in rows]==[(23,23,21),(24,24,23)]
assert all(x[k] is None for x in rows for k in ['observed','imputed','missing','missing_fraction'])
assert saved['active_questions']==[x['question_id'] for x in saved['answers']]
assert saved['judgment']=='some_concerns'
assert json.loads((R/'effective-model.json').read_text())==[{'model':'gpt-6-luna','effort':'medium'}]
assert r[1]['arguments']['guidance_profile']=='official_d3_prototype'
flow=next(x for x in r if x['item']=='item_13')['receipt']['data']['comparison_cards'][0]['participant_flow'];selected=next(x for x in r if x['tool']=='select_visual_evidence')['receipt']['data']['evidence']
assert all(x['figures'][0]['handle']==selected['handle'] and x['figures'][0]['render']==selected['render'] and x['figures'][0]['provenance']=='host_visual' for x in flow)
with sqlite3.connect(f'file:{R}/workspace/.rob2-kit/derivative.sqlite3?mode=ro',uri=True) as c:
 passages=[]
 for sid,pages in [('source_08c08c63f9bf7b55ef3ed5be07508039391adb4bb66eeeab2f437998e5cffc35',[4,5,6,7]),('source_c906a4d137a6dce28ffcf19a4f5067ad538bdbd51ac16755860339626047fc53',[5,6,7])]:
  for page in pages:
   text=c.execute('SELECT text FROM pages WHERE source_id=? AND page=?',(sid,page)).fetchone()[0];passages.append({'source_id':sid,'physical_page':page,'numbered_text':'\n'.join(f'{i}|{v}' for i,v in enumerate(text.splitlines(),1)),'scope':'independent source review; model deliveries recorded separately'})
write('scientific-review.json',{'qualitative_result':'partial success with factual scope contamination; algorithm path and label valid, scientific warrants largely defensible but refinable','answers':[(a['question_id'],a['answer'],a['justification']) for a in saved['answers']],'typed_unknowns_preserved':True,'visual_basis_received_in_model_flow_context':True,'canonical_server_label':'some_concerns','no_matched_accuracy_or_isolated_gain_claim':True,'factual_error':'Poor medication adherence belongs only to eliminatedCBD200 group in the figure, not selected CBD400/placebo. Mention in3.3 and counterevidence mixes scope. Selected-arm dropout/loss/missed visits still support possibility; label not corrected by operator.','method_review':'Baselineweek0 adjustment, timefixed effects, subject randomintercept and gamma outcome model are explicitly reported. MAR/Bayesian imputation not automatic proof or automatic failure. Model3.2PN is defensible given mechanism uncertainty but under-discusses these known components; no mandatoryMNAR analysis required. Age/sex adjustment is reported on native author7 lines25–27 outside selected7–24 range, despite read7–44.','model_reading':'Mainall10pages; main5render; author7lines7–44; supplementinventory and two lexicalqueries without hits, no supplementpage reads. No penalty for unrelated exhaustive reading, scoped limitations retained.','independent_relevant_source_passages':passages,'implementation_defect_after_trace_found':False,'runtime_changes_after_this_run':False,'reason_no_new_gate':'Prose uses an out-of-comparison reason from a correctly transcribed multipanel flow figure; counts, scope identities and visual provenance were preserved. No safe deterministic correction can infer clinical scope from arbitrary PDF prose. Adding per-trial parsing or forcing a scientific response would overfit.','original_answer_freeze_unchanged':True,'checks':'Offline assertions: saved counts/unknowns, canonical active path/label, exact model/profile, current visual locator delivery and original frozen hashes passed.'})
print('Offline native-state/provenance checks passed. No runtime defect inferred from model scope error.')
