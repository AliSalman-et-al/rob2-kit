"""Current projector replay on disposable copies; no model or scientific write."""
from pathlib import Path
import copy,hashlib,json,shutil,sqlite3,subprocess
from rob2_kit.application.domains import _host_asserted_sufficiency
from rob2_kit.application.trials import _review_domain_findings
from rob2_kit.application.source_handles import public_source_references
from rob2_kit.interfaces.mcp import server
ROOT=Path.cwd();D=ROOT/'docs/evaluation/2026-10-03-exscel-continuity-verdict';D.mkdir(exist_ok=True);scratch=ROOT.parent/'diagnostics/exscel-continuity-verdict';scratch.mkdir(exist_ok=True)
original=ROOT.parent/'diagnostics/frozen-exscel-bd92ec8/workspace';clone=scratch/'workspace';assert not clone.exists();shutil.copytree(original,clone)
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();protected=[original/'.rob2-kit'/x for x in ['canonical.sqlite3','working.sqlite3','derivative.sqlite3']];before={str(p):sha(p) for p in protected}
B=ROOT/'docs/evaluation/2026-10-03-exscel-host-recovery';path=B/'turn-0.events.jsonl';events={};raw={}
for number,line in enumerate(path.open(),1):
 row=json.loads(line);item=row.get('item',{})
 if row.get('type')=='item.completed':events[item['id']]=item;raw[item['id']]={'trace_line':number,'original_line_sha256':hashlib.sha256(line.encode()).hexdigest(),'line':line}
state=json.loads((B/'frozen-final-state.json').read_text());state_digest=sha(B/'frozen-final-state.json')
q3='sq:missing:evidence-unbiased';q5='sq:selection:multiple-analyses'
def answer(domain,q):return next(a for a in state['domain_records']['exscel:'+domain]['answers'] if a['question_id']==q)
d3=copy.deepcopy(answer('domain:missing',q3));d5=copy.deepcopy(answer('domain:selection',q5));saved3=next(a for a in events['item_19']['arguments']['answers'] if a['question_id']==q3);saved5=next(a for a in events['item_34']['arguments']['answers'] if a['question_id']==q5)
for exact,canonical in [(saved3,d3),(saved5,d5)]:
 for k in ['answer','justification','unknowns','counterevidence']:assert exact[k]==canonical[k]
cache=original/'.rob2-kit/working.sqlite3';assert not Path(str(cache)+'-wal').exists()
with sqlite3.connect(cache.resolve().as_uri()+'?mode=ro&immutable=1',uri=True) as c:working=json.loads(bytes(c.execute('SELECT payload FROM working_checkpoints').fetchone()[0]))
assert not working.get('premise_records')
(D/'original-working-checkpoint.json').write_text(json.dumps(working,indent=2)+'\n')
page188=next(p for p in events['item_32']['result']['structured_content']['data']['pages'] if p['page']==188);assert page188['passage_ref']=='eh_f3ad502fa6c18431' and not page188['truncated']
transitions=[]
for name,rev,domain_set in [('D3 saved',7,['randomization','deviations','missing']),('Later source read after D4',8,['randomization','deviations','missing','measurement']),('D5 saved',9,['randomization','deviations','missing','measurement','selection']),('Final Trial review',10,['randomization','deviations','missing','measurement','selection'])]:
 projected_state=copy.deepcopy(state);projected_state['revision']=rev;projected_state['domain_records']={k:v for k,v in state['domain_records'].items() if k in ['exscel:domain:'+x for x in domain_set]}
 findings=public_source_references(_review_domain_findings(clone,projected_state,'exscel'))
 a3=next(a for d in findings if d['domain_id']=='domain:missing' for a in d['answers'] if a['question_id']==q3)
 assert a3['justification']==d3['justification'] and a3['unknowns']==d3['unknowns']
 assert all(b['assertion']=='host_asserted' for b in a3['bases'])
 original_sufficiency=copy.deepcopy(state['domain_records']['exscel:domain:missing']['evidence_sufficiency']);transport=_host_asserted_sufficiency(original_sufficiency)
 assert original_sufficiency==state['domain_records']['exscel:domain:missing']['evidence_sufficiency']
 assert all(c['status']==old['status'] for c,old in zip(transport['claims'],original_sufficiency['claims'],strict=True))
 row={'transition':name,'revision':rev,'current_head_D3_answer':a3,'canonical_D3_identity_unchanged':state['domain_records']['exscel:domain:missing']['identity'],'current_transport_sufficiency':transport,'projection_scope':'Current HEAD review/provenance projection from retained canonical records, in a disposable copy. Source-delivery coverage is not backdated from the final cache; original trace establishes chronology.'}
 if 'selection' in domain_set:
  a5=next(a for d in findings if d['domain_id']=='domain:selection' for a in d['answers'] if a['question_id']==q5);assert a5['justification']==d5['justification'] and a5['unknowns']==d5['unknowns'];assert all(b['assertion']=='host_asserted' for b in a5['bases']);row['current_head_D5_answer']=a5
 transitions.append(row)
(D/'current-head-transitions.json').write_text(json.dumps(transitions,indent=2)+'\n')
snap=copy.deepcopy(events['item_35']['result']['structured_content']);snap['data']['domain_findings']=public_source_references(_review_domain_findings(clone,state,'exscel'));summary=server._project_review_trial(snap,cursor=None,selector=None,root=clone,persist=False)
for q,term in [(q3,'exists'),(q5,'imputation')]:
 a=next(a for d in summary['data']['domain_findings'] for a in d['answers'] if a['question_id']==q);assert term in json.dumps(a.get('warrant'))+json.dumps(a.get('unknowns'))
(D/'current-head-bounded-review.json').write_text(json.dumps(summary,indent=2)+'\n')
for label,domain,q in [('D3','domain:missing',q3),('D5','domain:selection',q5)]:
 detailed=server._project_review_trial(snap,cursor=None,selector={'domain_id':domain,'question_id':q},root=clone,persist=False);(D/(label+'-current-head-review-detail.json')).write_text(json.dumps(detailed,indent=2)+'\n')
for item_id in ['item_19','item_32','item_34','item_35','item_36','item_37']:(D/(item_id+'-original.jsonl')).write_text(raw[item_id]['line'])
assert before=={str(p):sha(p) for p in protected};assert state_digest==sha(B/'frozen-final-state.json')
report={'head':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'new_model_calls':0,'verdict':'Continuity works for the demonstrated EXSCEL sequence; no surviving application overwrite/projection loss or plan-to-result promotion found.','chronology':{'D3_saved':{'item':'item_19','revision':7,'exact_answer':saved3,'receipt':raw['item_19']['original_line_sha256']},'source_read':{'item':'item_32','revision':8,'exact_page188_receipt':page188,'receipt':raw['item_32']['original_line_sha256'],'effect':'Adds delivered primary evidence; does not infer or revise an answer/uncertainty.'},'D5_saved':{'item':'item_34','revision':9,'exact_answer':saved5,'receipt':raw['item_34']['original_line_sha256'],'effect':'Preserves host claim and mismatched selected bases; no actual-execution assertion introduced by application.'},'Trial_review':{'item':'item_35','revision':10,'selected_detail_items':['item_36','item_37'],'effect':'Current summary exposes D3 existence unknown and D5 plan claim; exact detail preserves facts, uncertainty and host_asserted bases. No automatic reconciliation.'}},'prior_work_reconciliation':{'counterpoint_cache_loss':'Existing direct_support/context preservation covers selected material and host inference distinctions. This replay does not repeat deletion/recovery tests or add that feature.','save_context_attribution':'Current _host_asserted_sufficiency is shared by saved receipt/context; canonical sufficiency and uncertainty remain unchanged. Existing tests cover consistency, not a new finding.','d789ea8_prose_restore':'Current bounded projection preserves the relevant authored pair. This replay confirms applicability to this sequence, not another restoration feature.','working_checkpoint':'Proposal-era observations/interpretations are stored, but no D3-specific WorkingPremiseRecord exists. The D3 existence uncertainty is an answer unknown. The proposed working-premise overwrite hypothesis does not apply here.'},'original_files_unchanged':before,'runtime_patch':False,'canonical_judgments_changed':False,'remaining_limitation':'The host did not revisit D3 uncertainty after reading an explicit plan and attached wrong D5 support; correct links do not establish performed analysis or robustness. Human/host interpretation remains required.','future_paid_check_frozen':False}
(D/'verdict.json').write_text(json.dumps(report,indent=2)+'\n');print(report['verdict']);print('Current bounded review bytes',server._review_transport_bytes(summary));print('Original databases unchanged; no model or scientific write.')
