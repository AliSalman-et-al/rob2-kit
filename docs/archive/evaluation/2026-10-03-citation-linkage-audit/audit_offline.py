"""Read-only receipt/handle linkage audit. Integrity checks do not score entailment."""
from pathlib import Path
import hashlib,json,zipfile
ROOT=Path.cwd();D=ROOT/'docs/evaluation/2026-10-03-citation-linkage-audit';D.mkdir(exist_ok=True);rawdir=D/'raw-receipts';rawdir.mkdir(exist_ok=True)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def catalog(paths):
 pages={};records={};sources={};calls=[];trace_hashes={}
 for path in paths:
  trace_hashes[str(path.relative_to(ROOT))]=sha(path)
  for number,line in enumerate(path.open(),1):
   row=json.loads(line);item=row.get('item',{})
   if row.get('type')!='item.completed':continue
   result=item.get('result') or {};structured=result.get('structured_content')
   if not isinstance(structured,dict):continue
   def visit(v):
    if isinstance(v,dict):
     handle=v.get('handle')
     if isinstance(handle,str) and isinstance(v.get('identity'),str) and 'source_id' in v:records.setdefault(handle,[]).append(v)
     if v.get('media_type') and isinstance(v.get('sha256'),str) and isinstance(v.get('id'),str):sources[v['id']]=v
     for x in v.values():visit(x)
    elif isinstance(v,list):
     for x in v:visit(x)
   visit(structured)
   calls.append({'item':item,'path':path,'line':number,'raw':line})
   if item.get('tool')=='read_pages':
    for p in structured.get('data',{}).get('pages',[]):
     h=p.get('passage_ref')
     if h:pages.setdefault(h,[]).append({'page_receipt':p,'call':calls[-1]})
 return {'pages':pages,'records':records,'sources':sources,'calls':calls,'trace_hashes':trace_hashes}
def binding(cat,h,label):
 allrows=cat['records'].get(h,[]);locators={(r['source_id'],r.get('page'),r.get('start_line'),r.get('end_line')) for r in allrows}
 refs=cat['pages'].get(h,[]);locators.update((r['page_receipt']['source_id'],r['page_receipt']['page'],r['page_receipt']['returned_start_line'],r['page_receipt']['returned_end_line']) for r in refs)
 assert len(locators)==1,(h,locators)
 identities={r['identity'] for r in allrows};assert len(identities)<=1,(h,identities)
 if identities:assert h=='eh_'+next(iter(identities)).split(':',1)[1][:16]
 chosen=refs[0] if refs else None;record=allrows[0] if allrows else None
 out={'selected_handle':h,'selected_identity':next(iter(identities)) if identities else None,'unambiguous_source_page_span':list(next(iter(locators))),'selected_record':record,'original_page_receipt':chosen['page_receipt'] if chosen else None,'handle_collision_observed':False}
 if chosen:
  call=chosen['call'];name=label+'-'+h+'.jsonl';(rawdir/name).write_text(call['raw']);out.update({'receipt_artifact':'raw-receipts/'+name,'receipt_bytes_sha256':sha(rawdir/name),'original_trace':str(call['path'].relative_to(ROOT)),'original_trace_line':call['line'],'original_item_id':call['item']['id'],'original_request':call['item']['arguments'],'individual_page_locator_inside_group':True})
 return out
G=catalog([ROOT/'docs/evaluation/2026-10-03-gupta-full-validation/turn-1.jsonl',ROOT/'docs/evaluation/2026-10-03-gupta-full-validation/turn-2.jsonl'])
E=catalog([ROOT/'docs/evaluation/2026-10-03-exscel-host-recovery/turn-0.events.jsonl'])
def saved_answer(cat,domain,question,label):
 c=next(c for c in cat['calls'] if c['item'].get('tool')=='save_domain_judgment' and c['item']['arguments'].get('domain_id')==domain);answer=next(a for a in c['item']['arguments']['answers'] if a['question_id']==question);name=label+'-original-save.jsonl';(rawdir/name).write_text(c['raw']);return {'exact_final_saved_claim':answer,'save_receipt_artifact':'raw-receipts/'+name,'save_receipt_sha256':sha(rawdir/name),'original_trace_line':c['line'],'original_item_id':c['item']['id'],'basis_links':[binding(cat,b['evidence'],label) for b in answer['bases']]}
g=saved_answer(G,'domain:measurement','sq:measurement:differential','gupta');e=saved_answer(E,'domain:selection','sq:selection:multiple-analyses','exscel')
prep=json.loads((ROOT/'docs/evaluation/2026-10-03-gupta-real-image-reading/next-citation-audit-preparation.json').read_text());gh=prep['correct_source_control']['passage_ref'];g['already_read_correct_source']=binding(G,gh,'gupta-correct-source');e['already_read_correct_source']=binding(E,'eh_f3ad502fa6c18431','exscel-correct-source')
g['operator_conclusion']='13/86 vs13/94 testing-omission counts are in main physical7; submitted basis handles resolve to appendix14, main3 and main6. Citation selection/entailment mismatch, not lost or aliased mapping. This does not establish D4Low is wrong.'
e['operator_conclusion']='Missing-followup event-imputation plan is on delivered physical188; submitted direct-support handles resolve to187/192, context to main6. Other parts of the broader justification have support, but this plan phrase lacks its own saved primary support link. Plan is not execution/robustness.'
C=json.loads((ROOT/'docs/evaluation/2026-10-03-exscel-review-response-d789ea8/code-dapa-comparator.json').read_text());archive=Path(C['archive']);assert sha(archive)==C['archive_sha256']
with zipfile.ZipFile(archive) as z:
 matched=[(n,json.loads(z.read(n))) for n in z.namelist() if n.startswith('evidence/') and n.endswith('.json')];name,ev=next((n,x) for n,x in matched if x.get('identity')==C['evidence']['identity']);assert ev==C['evidence'];(D/'dapa-original-evidence.json').write_bytes(z.read(name));manifest=json.loads(z.read('manifest.json'));(D/'dapa-archive-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
C['original_evidence_member']=name;C['original_evidence_bytes_sha256']=sha(D/'dapa-original-evidence.json');C['operator_conclusion']='The specific protocol-requires-final-amendments-before-unblinding claim is stated in the actual selected physical161 lines16–20 quote. This supports planned timing, not actual compliance; no source-link seam in this positive control.'
original=Path('/home/ali/Documents/Code/rob2-kit-benchmark/rob2-meta-set-full-2026-09-29/trials');sources=[]
for trial,names in [('gupta-2024',['NEJMoa2305582.pdf','nejmoa2305582_appendix.pdf']),('exscel',['NEJMoa1612917.pdf','nejmoa1612917_protocol.pdf'])]:
 for name in names:
  p=original/trial/name;sources.append({'trial':trial,'path':str(p),'sha256':sha(p)})
assert sources[-1]['sha256']=='d3498516286f49f1d609124999be3d44a7a8ddac46eb70d4542395ffabcc96a2'
report={'scope':'offline source linkage, not semantic validation or domain accuracy','new_model_calls':0,'runtime_change_justified':False,'case_negatives':{'gupta':g,'exscel':e},'correct_source_control_from_original_Code_archive':C,'original_Code_source_files':sources,'original_trace_hashes':{**G['trace_hashes'],**E['trace_hashes']},'retained_historical_verification':{'exscel':json.loads((ROOT/'docs/evaluation/2026-10-03-exscel-host-recovery/both-verifiers.json').read_text()),'not_reverified_or_modified':True},'integrity_check_scope':['Every audited selected handle resolves to one source/page/inclusive line span; no observed collision.','Every known full identity matches its exposed handle prefix.','Receipt artifacts retain exact original JSONL line bytes, with source text and item/request unchanged.','Correct-source material is linked separately; it is never auto-added to original bases.'],'limits':['The logs establish clear locators; they do not establish causal attribution to a particular cognitive mechanism or show ergonomic ease quantitatively.','Grouped multipage content and long context can still impose effort, but no missing per-page handle or source/page alias was demonstrated.','Historical wrong selections remain wrong selections; a valid role/handle is not proof of entailment.','Known historical summary prose loss, source-image transport failure and diagnostic coverage omission are separate resolved/recorded issues; none explains away these saved selections.']}
(D/'audit.json').write_text(json.dumps(report,indent=2)+'\n');print('Negative links:',{k:[v['unambiguous_source_page_span'] for v in x['basis_links']] for k,x in report['case_negatives'].items()});print('Positive Code control:',C['evidence']['page'],C['evidence']['start_line'],C['evidence']['end_line']);print('No runtime mapping seam demonstrated.')

# Add source-file and image provenance without interpreting scientific entailment.
report['source_catalog']={'gupta':G['sources'],'exscel':E['sources']}
for trial,cat,dirname in [('gupta',G,'gupta-2024'),('exscel',E,'exscel')]:
 used={b['unambiguous_source_page_span'][0] for b in report['case_negatives'][trial]['basis_links']}
 for source_id in used:
  source=cat['sources'][source_id];sourcefile=original/dirname/source['logical_path'];assert source['sha256']=='sha256:'+sha(sourcefile)
for case,cat in [('gupta',G),('exscel',E)]:
 for b in report['case_negatives'][case]['basis_links']:
  b['source_metadata']=cat['sources'][b['unambiguous_source_page_span'][0]]
with zipfile.ZipFile(archive) as z:
 canonical=json.loads(z.read('canonical.json'));dapa_sources=canonical['batch']['trials'][0]['sources'];dapa_source=next(s for s in dapa_sources if s['id']==C['evidence']['source_id'])
 dapa_file=original/'dapa-hf'/dapa_source['logical_path'];assert dapa_source['sha256']=='sha256:'+sha(dapa_file);C['source_metadata']=dapa_source;C['original_Code_source_path']=str(dapa_file)
render=[]
for name in ['turn-1.jsonl','turn-2.jsonl']:
 path=ROOT/'docs/evaluation/2026-10-03-gupta-full-validation'/name
 for number,line in enumerate(path.open(),1):
  row=json.loads(line);item=row.get('item',{})
  if row.get('type')=='item.completed' and item.get('tool')=='render_page':
   value=(item.get('result') or {}).get('structured_content')
   if not isinstance(value,dict):continue
   filename='gupta-render-'+item['id']+'.jsonl';(rawdir/filename).write_text(line)
   render.append({'original_item_id':item['id'],'original_request':item['arguments'],'original_trace':str(path.relative_to(ROOT)),'original_trace_line':number,'receipt':value.get('data',{}),'original_receipt_sha256':hashlib.sha256(line.encode()).hexdigest(),'artifact':'raw-receipts/'+filename})
image_dir=ROOT/'docs/evaluation/2026-10-03-gupta-real-image-reading';verified=json.loads((image_dir/'adjudication.json').read_text())
report['visual_provenance_audit']={'closed_Gupta_render_calls':render,'original_transport_failure':'PNG and exact source/page/render/delivery receipt present in MCP result; original native model shortcut dropped PNG. Fixed separately. Negative numeric citations are narrative selections, not visual bindings.','real_reading_positive':{'artifact':str(image_dir.relative_to(ROOT)),'answer_sha256':sha(image_dir/'response.txt'),'actual_render_receipt':verified['actual_render_receipt'],'native_png_sha256':verified['native_image_sha256'],'selected_visual_evidence_handle':None,'selection_scope':'Reading diagnostic required no Domain evidence selection; native image comprehension is not a saved visual basis.','image_only_observation':verified['image_exclusive_observation'],'legend_overstatement':verified['qualifications'][0]},'separation':'Successful image comprehension, minor legend overstatement, numeric mis-citation and historical transport failure are separate findings.'}
bundle=next((ROOT/'docs/evaluation/2026-10-03-exscel-host-recovery').glob('*.rob2.zip'));report['retained_historical_verification']['exscel_artifact']={'path':str(bundle.relative_to(ROOT)),'zip_sha256':sha(bundle),'no_new_verification_run':True}
report['future_paid_check_frozen']=False
report['reason_no_new_paid_check']='No runtime seam or new mechanism to isolate was demonstrated. Do not spend on another response to the same known citation fact.'
(D/'audit.json').write_text(json.dumps(report,indent=2)+'\n')
print('Original Code source hashes, selected receipt boundaries and independent image provenance verified.')

# Recover the uncited-but-delivered full identity from the preserved closed cache.
# Immutable read-only SQLite avoids any application initialization or ledger write.
import sqlite3
cache=ROOT.parent/'diagnostics/frozen-exscel-bd92ec8/workspace/.rob2-kit/derivative.sqlite3'
assert not Path(str(cache)+'-wal').exists()
cache_before=sha(cache)
with sqlite3.connect(cache.resolve().as_uri()+'?mode=ro&immutable=1',uri=True) as connection:
 identity,payload=connection.execute(
  'SELECT identity,payload FROM evidence_handles WHERE identity LIKE ?',
  ('sha256:f3ad502fa6c18431%',)
 ).fetchone()
assert sha(cache)==cache_before
payload=bytes(payload);ev188=json.loads(payload);assert ev188['identity']==identity
assert ev188['handle']=='eh_f3ad502fa6c18431'
correct=report['case_negatives']['exscel']['already_read_correct_source'];page=correct['original_page_receipt']
assert (ev188['page'],ev188['start_line'],ev188['end_line'])==(188,1,43)
assert ev188['quote']=='\n'.join(x.split('|',1)[1] for x in page['numbered_text'].splitlines())
(D/'exscel-read-p188-evidence.json').write_bytes(payload)
correct['selected_identity']=identity
correct['registered_original_read_evidence']=ev188
correct['full_identity_provenance']={'cache_path':str(cache),'read_mode':'ro+immutable','cache_sha256_before_and_after':cache_before,'evidence_member_sha256':sha(D/'exscel-read-p188-evidence.json'),'note':'This is an already-issued read handle, not support selected in the final D5 basis.'}
report['guidance_change']='Consolidated duplicate review/reference prose; no new runtime rule, input field or semantic validator.'
(D/'audit.json').write_text(json.dumps(report,indent=2)+'\n')
print('Preserved EXSCEL188 full identity recovered without changing closed cache.')
