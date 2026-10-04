"""Offline adjudication recorded only after answer-freeze.json; no model call."""
from pathlib import Path
import hashlib
import json

R=Path(__file__).resolve().parent
ROOT=R.parents[2]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(name,x):(R/name).write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
freeze=json.loads((R/'answer-freeze.json').read_text())
assert all(sha(R/('panel-'+name))==digest for name,digest in freeze.items())
m=json.loads((R/'manifest.json').read_text())
assert sha(R/'private-scoring-units.json')==m['scoring_units_sha256']
assert sha(R/'private-criteria.md')==m['private_criteria_sha256']
assert all(sha(Path(path))==h for path,h in {**m['existing_rollout_hashes'],**m['protected_bundle_hashes']}.items())
units=json.loads((R/'private-scoring-units.json').read_text())
# One outcome per predeclared mechanical sentence/uncertainty unit, in original order.
coverage=['full','full','full','not_explicit','full','partial','full','full','partial','partial','full','full','full','partial','full','full','full','full','full','full','full','full','partial']
findings=[
 'Endpoint and time supported; objective recording described as not directly established, a conservative qualification rather than global falsity.',
 'BPD thresholds and subjective oxygen-dependency testing correctly attributed to appendix p14 and main p3.',
 'Structured/clinically relevant characterization accepted as reasonable; however, denial of support for some clinical judgment is a false alarm on a qualified inference from the explicit subjective oxygen-need statement. External-validation scope is appropriately limited.',
 'The final RoB interpretation is not separately classified. No replacement judgment requested or produced; count this unit transparently rather than as an implicit pass.',
 'Tool/image-inspection uncertainty cannot be verified from text spans, correctly retained.',
 'Common approach accepted as inference, not explicit group-specific fact; blinding support found in main p2, which is exported for the assessor-awareness claim rather than bound to this differential warrant. Original per-claim citation mismatch is not explicitly distinguished.',
 'Known numeric clause correctly classified as not established by supplied citations; no claim that the counts are globally false. Proportion-similarity interpretation is not separately evaluated.',
 'Qualifies the absence of group-specific method wording without asserting contradiction; no global proof of equivalence.',
 'Assessment opportunity is correctly left unestablished; differential-measurement conclusion is only indirectly addressed through common approach inference.',
 'Reasons for missing oxygen assessments left unexplained; availability and D3/D4 domain-allocation clauses are not individually evaluated.',
 'Assessor-blinding statement accurately supported by article p2 lines68-70.',
 'Direct assessor-awareness rationale accepted as fair description.',
 'DAPA protocol planning requirement correctly supported, without converting it into proof of compliance.',
 'SAP date, endpoint and reported protocol/SAP adherence addressed; Cox prespecification attribution is separately qualified under the multiple-analyses warrant, not fully split here.',
 'Actual HR/CI and ITT supported, adjudication conduct correctly not inferred as directly confirmed solely from SAP plan.',
 'Before-unblinding prespecification treated as inference from protocol commitment with timing uncertainty retained.',
 'Exact finalization/data-access timing uncertainty explicitly preserved.',
 'Primary time-to-first composite correctly supported by SAP p241.',
 'Outcome distinction addressed, but locator p5 lines42-55 is secondary/recurrent-result text, not the primary component-result passage at p5 lines27-38. This is a source-range attribution defect despite support elsewhere in the supplied p5 span.',
 'No-selection statement explicitly limited to supplied spans, not direct proof or contradiction.',
 'Additional real attribution gap detected: selected SAP p241 does not specify Cox stratification/adjustment; article p4 specifies performed model, not this SAP prespecification.',
 'Reported adherence and performed ITT/Cox method correctly grounded in main p2/p4.',
 'Secondary/recurrent analyses and results-driven-selection inference addressed across the selection paragraphs; separately reported subgroup analysis clause not explicitly checked.',
]
assert len(units)==len(coverage)==len(findings)==23
rows=[{**unit,'coverage':c,'finding':f} for unit,c,f in zip(units,coverage,findings,strict=True)]
write('unit-adjudication.json',rows)
write('adjudication.json',{
 'decision':'Reject reviewer adoption for now; keep deterministic exporter as an offline model-free diagnostic.',
 'research_question_result':'Known unsupported numeric attribution detected, but feedback is not sufficiently faithful for adoption as a factual reviewer.',
 'output_frozen_before_adjudication':True,'protected_prior_rollouts_and_bundles_unchanged':True,
 'full_panel_counts':{'domain_warrants':6,'domain_warrants_addressed':6,'predeclared_sentence_or_uncertainty_units':23,'warrant_sentence_units':20,'uncertainty_units':3,'counterevidence_units':0,'fully_addressed_units':17,'partially_addressed_units':5,'not_explicitly_addressed_units':1},
 'detection':{'predeclared_numeric_gap_detected':1,'predeclared_numeric_gaps':1,'additional_real_attribution_gap':1,'additional_gap':'SAP Cox-model prescription attributed to p241 without selected SAP method support; performed model is in main p4.'},
 'feedback_errors':{'confirmed_inferential_false_alarm_units':1,'wrong_supporting_line_range_units':1,'global_falsity_claims':0,'explicit_false_contradictions':0,'nonexistent_source_or_page_locators':0,'forced_RoB_revisions':0},
 'correct_source_controls':{'controls':2,'preserved':2,'items':['Gupta assessor blinding directly supported main p2','DAPA before-unblinding SAP-amendment requirement is plan, not confirmed compliance']},
 'inferential_controls':'Structured/clinically relevant and common application inference accepted; some clinical judgment falsely treated as unsupported. Proportion similarity not separately evaluated once numeric support was absent. Do not claim all inferential controls passed.',
 'citation_link_limit':'Uses main p2 support from another claim within the Domain without explicitly flagging its absence from the differential warrant citations. Pooled source support and original claim-specific attribution are distinct.',
 'rejection_reason':'A citation audit that introduces a source-range attribution defect and a false alarm on a qualified inference cannot yet be relied on for feedback. Detecting the known gap alone is insufficient. This applies the predeclared material-factual-failure rejection criterion; it does not turn every conservative wording qualification into failure.',
 'no_causal_claim':'Task, source pooling, history and obligations differ from native continuation; no anchoring or capacity attribution.',
 'no_automatic_changes':True,'no_retry_or_continuation':True,
})
run=json.loads((R/'panel-run.json').read_text());u=run['usage']
write('cost-comparison.json',{'new_audit':{**u,'uncached_input_tokens':u['input_tokens']-u['cached_input_tokens'],'responses':run['provider_response_count'],'turns':1,'tools':run['tool_calls'],'wall_seconds':run['elapsed_seconds']},'native_fork':{'input_tokens':765107,'cached_input_tokens':683520,'uncached_input_tokens':81587,'output_tokens':2476,'reasoning_output_tokens':566,'turns':1,'tools':13,'wall_seconds':77.21926663599152},'original_supplied_clause_panel':{'input_tokens':16807,'cached_input_tokens':0,'output_tokens':663,'reasoning_output_tokens':0,'responses':1,'tools':0,'wall_seconds':18.677928150995285},'audit_input_as_fraction_of_native_cumulative_input':u['input_tokens']/765107,'audit_uncached_as_fraction_of_native_uncached_input':(u['input_tokens']-u['cached_input_tokens'])/81587,'comparison_limit':'Extra audit cost, not cost saving. Tasks/scopes differ; reasoning tokens are included in output. This new response is separate, not inherited native usage.'})
# Preserve private stderr provenance without publishing raw host diagnostics.
err=R/'panel-stderr.log';destination=ROOT.parent/'diagnostics/factual-audit-feasibility-20261004-stderr.log'
assert not destination.exists()
write('stderr-provenance.json',{'sha256':sha(err),'bytes':err.stat().st_size,'private_path':str(destination)})
err.rename(destination)
print('23 units adjudicated after freeze; no original rollouts/bundles changed.')
