"""Manual grouped flag explanations and full control before/after table; no model."""
from __future__ import annotations
import json,hashlib
from pathlib import Path
R=Path(__file__).resolve().parent
# Explanations frozen after inspecting exact selected material, not used as screening rules.
NOTES={
 ('albert-2013','sq:missing:data-available'):('representational_or_derived','Arm fractions assemble separately reported n=77/90 and 67/72. Total 144/162 is explicitly supported by the p4 counts but not written as a slash literal. Missing ratios use reported dropout counts 13 and 5 (p5), or subtraction 90-77=13 and 72-67=5. Ratios are legitimate; no arithmetic or exact ratio typography is required of the article.'),
 ('dapa-hf','sq:missing:data-available'):('true_selected_span_gap_correct_fact_elsewhere','The selected main p3 flow reports 14/20 incomplete follow-up, two unknown vital statuses and randomized n=2373/2371, but not event totals 386/502. Those counts are correctly reported on the same main source p1 lines40–41 (also p5/p8). This is a second real attribution gap, not false counts or a contradiction; it is not counted as representational noise.'),
 ('sustain-6','sq:missing:data-available'):('representational_or_derived','1623/1648 and 1609/1649 assemble counts in the selected host_visual disposition transcription. 3232/3297 combines the main p4 follow-up count with the same selected figure total. All underlying counts and percentages are reported; slash typography is absent, not support.'),
 ('monarch-2','sq:missing:data-available'):('representational_or_derived','Source p2 reports lost-to-follow-up n=6 and n=4 and primary n=669. 10=6+4; 10/669*100=1.494768%, rounded about 1.5%. The source need not print the sum, fraction or rounded percentage. All randomized primary-cohort counts are distinct from exploratory n=44.'),
 ('getgood-2020','sq:missing:data-available'):('representational_or_derived','Selected main p5 lines110–125 reports lost n=8 and withdrawn n=6 in ACLR: combined 14=8+6 (also 312-298). Combined LET loss 15=10+5 (306-291) is equally legitimate. The matcher finds 15 via an unrelated 15% PRO missingness value, illustrating that a present value can falsely reassure about its semantic binding.'),
 ('nefigard','sq:missing:data-available'):('representational_or_derived','Figure transcription gives denominators 182 and nominal visit counts 149/146, with broader-window counts 161/165 supported by main p7 and Figure S2. Ratios are assembled, not verbatim. 149/182*100=81.8681%, rounded 82%; 146/182*100=80.2198%, rounded 80%. 364=182+182 (or 366-2 incorrectly randomized). No missing literal is evidence these claims contradict the source.'),
 ('award-1-2014','sq:deviations:substantial-impact'):('representational_or_derived','Main p3 writes Two patients and randomized 978. 2/978*100=0.204499%, rounded about 0.2%. The scanner does not understand written Two; that is an explicit blind spot, not an absent factual count. The inference role is appropriate for impact, but basis roles are not per-clause calculation labels.'),
 ('attal-2016','sq:missing:data-available'):('representational_or_derived','Supplement p15 lines9–15 reports out of 1650 records, 131 missing and out of 396, 29 missing, with 7.9%/7.3%. Slash fraction spelling is assembled. The warrant adds a conventional thousands comma to 1650; numeric correctness is unchanged. 131/1650*100=7.93939% and 29/396*100=7.32323%, matching reported rounding. These are records, not participant-availability percentages.'),
 ('nefigard','sq:missing:evidence-unbiased'):('representational_or_derived','All 11 flagged point-estimate/CI bound values are in selected Table S2 p10. The article spells decimals with middle dot (5·14, 3·24, 7·58, 5·05, 7·38, 5·16, 3·07, 7·81, 4·79, 2·92, 7·16); the warrant uses a decimal point. Existing canonical presentation normalization leaves the middle dot unchanged. This is publication typography, not contradictory estimates or missing support.'),
}
CLEAR={
 ('canvas-program','sq:missing:evidence-unbiased'):'Reported/imputed HR 0.86/0.85 and 95% CI 0.75–0.97 are literal in selected p6; no flag. Literal matching does not evaluate the plausibility of its imputation assumptions.',
 ('exscel','sq:missing:data-available'):'95.1%/94.5% observed-versus-expected MACE follow-up in stored figure transcription; 96.2% trial completion and 98.8% vital status in selected main prose. Source-specific meanings remain different.',
 ('leader','sq:missing:data-available'):'Completion/vital-status/arm-loss percentages are in the main text and stored figure transcription; all scalar values match. Endpoint-specific missingness is not proved by this test.',
 ('declare-timi-58','sq:deviations:substantial-impact'):'30 excluded of 17,160 randomized are explicit in the cited source. Keeping inference-role evidence avoids an arbitrary role-based false flag.',
 ('pioneer-6','sq:missing:data-available'):'3172/3183 are written as separate counts, not a slash expression in this warrant; 99.7% and 11 noncompleters are directly reported. No flag. Protocol follow-up intent does not by itself prove conduct.',
 ('attal-2016','sq:measurement:influence-likely'):'13 participants are directly transcribed in a basis tagged inference because the downstream expectancy implication is inferred. Filtering out inference bases would discard a correct numerical premise.',
 ('albert-2013','sq:measurement:method-inappropriate'):'23 items and 0–23 range match canonical dash normalization and the source text. No unit, validity or endpoint entailment is certified.',
 ('monarch-2','sq:measurement:differential'):'RECIST 1.1 and 8/12/2-week numeric literals are supported by selected article p3. Written year one is outside digit extraction; there is no conversion or unit check.',
}
def main()->None:
 sample=json.loads((R/'sample.json').read_text(encoding='utf-8'));primary=json.loads((R/'results.json').read_text(encoding='utf-8'));sens=json.loads((R/'sensitivity-results.json').read_text(encoding='utf-8'))
 rows=[]
 for s,p,x in zip(sample,primary['results'],sens['results'],strict=True):
  key=(p['case'],p['question']);assert key==(x['case'],x['question'])
  if p['sample_role']=='known_gap':kind='known_selected_span_gap';explanation='Main p7 lines85–94 correctly reports 13/86 and 13/94, not in the three selected D4 spans. Primary flags both fractions; component sensitivity finds 86 and 94 absent while 13 is present elsewhere in selected material. No inferred contradiction or risk change.'
  elif p['flagged']:kind,explanation=NOTES[key]
  else:kind='no_literal_absence_flag';explanation=CLEAR[key]
  rows.append({'case':p['case'],'question':p['question'],'primary_flags':p['absent'],'sensitivity_flags':x['absent_values'],'classification':kind,'explanation':explanation,'before_runtime_annotation':None,'after_runtime_annotation':None,'reason_no_after_annotation':'Rejected offline candidate; no prototype installed','basis_roles':p['basis_roles'],'has_existing_recovery_action':bool(p['existing_exact_recovery_actions'])})
 controls=[r for r in rows if r['case']!='gupta-2024'];noise=[r for r in controls if r['classification']=='representational_or_derived'];gaps=[r for r in controls if r['classification']=='true_selected_span_gap_correct_fact_elsewhere']
 report={'decision':'Reject runtime opt-in annotation for now; no validator, automatic citation repair, required fields or default changes. Cheap literal/value absence cannot separate common legitimate derivations from unsupported numerical premises with current clause bindings.','primary':{'flagged_controls':9,'controls':17,'noisy_control_answers':len(noise),'noisy_expression_flags':sum(len(r['primary_flags']) for r in noise),'additional_real_attribution_gap_answers':len(gaps),'additional_real_attribution_gap_expressions':sum(len(r['primary_flags']) for r in gaps)},'exploratory_component':{'flagged_controls':5,'controls':17,'noisy_control_answers':sum(bool(r['sensitivity_flags']) for r in noise),'noisy_value_flags':sum(len(r['sensitivity_flags']) for r in noise),'correct_fact_elsewhere_gap_values':sum(len(r['sensitivity_flags']) for r in gaps),'not_independent_validation':True},'rows':rows}
 (R/'adjudication.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 lines=['| Case / question | Frozen primary flags | Exploratory component flags | Interpretation |','|---|---|---|---|']
 for r in rows:lines.append('| '+r['case']+' / '+r['question'].split(':')[-1]+' | '+(', '.join(r['primary_flags']) or 'none')+' | '+(', '.join(r['sensitivity_flags']) or 'none')+' | '+r['classification'].replace('_',' ')+' |')
 (R/'before-after.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
 # Freeze model-free outcome only after all flags were individually covered.
 files=['results.json','sensitivity-results.json','adjudication.json','before-after.md','elsewhere-context.json','next-scientific-issue.json']
 (R/'outcome-freeze.json').write_text(json.dumps({n:hashlib.sha256((R/n).read_bytes()).hexdigest() for n in files},indent=2)+'\n')
 print(json.dumps({k:v for k,v in report.items() if k!='rows'},indent=2))
if __name__=='__main__':main()
