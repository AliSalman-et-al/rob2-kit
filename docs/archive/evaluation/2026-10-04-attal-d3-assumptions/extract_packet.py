"""Read-only extraction of the scientific audit packet; no workflow operations."""
from __future__ import annotations
import hashlib,json,re
from decimal import Decimal
from pathlib import Path
from rob2_kit.packs.scientific import _OFFICIAL_ELABORATIONS,_GUIDANCE_VERSION,_GUIDANCE_SOURCE_SHA256
R=Path(__file__).resolve().parent
B=Path('/home/ali/Documents/Code/rob2-kit-benchmark/benchmark-luna6-medium-2026-10-01/cases/attal-2016')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(name,x):(R/name).write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
proof=json.loads((R/'provenance.json').read_text())
for p,h in proof['original_files'].items():assert sha(Path(p))==h
pages=json.loads((R/'captured-projections.json').read_text());supp=proof['source_inventory'][0]['id'];main=proof['source_inventory'][1]['id']
def window(source,page,start,end):
 raw=next(x['numbered_text'] for x in pages if x['source_id']==source and x['page']==page)
 lines=raw.splitlines();return {'source_id':source,'physical_page':page,'start_line':start,'end_line':end,'numbered_text':'\n'.join(lines[start-1:end]),'selection_status':'offline audit window, not a newly selected assessment Evidence'}
# Fixed physical source rows independently checked against original PDF pixels.
specs=[('LOCF',13,19,21,41,43),('Interpolation, 2 adjacent points',13,47,49,69,71),('Interpolation, 3 adjacent points',13,75,77,97,99),('Maximum likelihood / PROC MIXED',13,103,105,125,127),('MCMC MI, five datasets',14,3,5,25,27)]
methods=[]
for method,page,heading,value_start,week_heading,week_value in specs:
 raw=next(x['numbered_text'] for x in pages if x['source_id']==supp and x['page']==page).splitlines()
 def triplet(start):return [Decimal(raw[i-1].split('|',1)[1]) for i in range(start,start+3)]
 estimate,lo,hi=triplet(value_start);w,wlo,whi=triplet(week_value)
 methods.append({'method':method,'overall_estimate':str(estimate),'overall_ci':[str(lo),str(hi)],'week24_estimate':str(w),'week24_ci':[str(wlo),str(whi)],'p_value':'<.0001','overall_source':window(supp,page,heading,value_start+3),'week24_source':window(supp,page,week_heading,week_value+3)})
write('sensitivity-results.json',{'approved_result':'Overall adjusted weekly pain-intensity difference over 24 weeks; week24 row is a distinct point-specific contrast','methods':methods,'overall_abs_estimate_range':[str(min(abs(Decimal(m['overall_estimate'])) for m in methods)),str(max(abs(Decimal(m['overall_estimate'])) for m in methods))],'attenuation_vs_locf_absolute':str(Decimal('0.768')-Decimal('0.650')),'attenuation_vs_locf_percent':str((Decimal('0.768')-Decimal('0.650'))/Decimal('0.768')*100),'limitation':'Descriptive variation only. Significance/overlapping CIs do not establish absence of missing-data bias or clinical invariance.'})
patterns=['imput','interpol','missing at random','not at random','mnar','missing pattern','proc mixed','sensitivity','delta','tipping','jump to','reference-based','covariate']
hits=[]
for p in pages:
 for line in p['numbered_text'].splitlines():
  terms=[x for x in patterns if x in line.lower()]
  if terms:hits.append({'source_id':p['source_id'],'page':p['page'],'line':int(line.split('|',1)[0]),'text':line.split('|',1)[1],'terms':terms})
write('source-coverage.json',{'captured_pages':len(pages),'source_scope':'All captured Attal main/supplement/registry projections only','query_terms':patterns,'hits':hits,'negative_scope':'No explicit delta, tipping-point, reference-based or other stated MNAR departure identified in these captured sources; no SAS code/IPD or imputation-variable specification found. This is scoped report absence, not proof no unpublished analysis exists.'})
write('mechanism-evidence.json',{'windows':[window(main,4,29,62),window(main,4,78,122),window(main,5,43,54),window(supp,13,3,10),window(supp,14,31,33),window(supp,15,7,15),window(main,10,18,33)],'visual_consortraw':{'all_randomized':[34,34],'analysis_cohort':[34,32],'not_first_administration_placebo':['one patient refusal','one no baseline assessment of pain'],'not_second_administration_active':['one absence of efficacy','one first administration too painful'],'not_second_administration_placebo':['four absence of efficacy','two first administration too painful'],'later_discontinued_active':['two absence of efficacy','one died'],'later_discontinued_placebo':['three absence of efficacy'],'final_week24_safety_assessment':[29,23]},'qualification':'These categories are direct visual observations from main-p4-consort.png. Final safety assessment is not an observed primary-pain denominator. Missing second dose, study discontinuation and missing pain-record observations are related but not interchangeable; source does not link each category to particular missing records.'})
# Original delivered context and actual source windows, never another native call.
rows=[json.loads(line) for line in (B/'turn-2.jsonl').read_text().splitlines()];items=[row['item'] for row in rows if row.get('type')=='item.completed' and row.get('item',{}).get('type')=='mcp_tool_call'];context=[];read=None
for i in items:
 if i['id'] in ['item_35','item_36','item_37','item_38']:
  d=i.get('result',{}).get('structured_content',{});d=d.get('data',d)
  if not d:
   for block in i.get('result',{}).get('content',[]):
    if block.get('type')=='text':
     try:d=json.loads(block['text']);d=d.get('data',d)
     except ValueError:pass
  context.append({'item':i['id'],'arguments':i['arguments'],'questions':d.get('questions'),'guidance':d.get('guidance'),'official_guidance':d.get('official_guidance'),'pack':d.get('pack')})
 if i['id']=='item_40':
  e=i['result'].get('structured_content',{});e=e.get('data',e)
  read={'item':i['id'],'arguments':i['arguments'],'delivered_pages':e.get('pages'),'error':i.get('error')}
write('original-delivery.json',{'log':str(B/'turn-2.jsonl'),'log_sha256':sha(B/'turn-2.jsonl'),'context':context,'supplement_table_read':read,'interpretation':'Original model received actual tables before saving, not merely the narrative claim of invariance; no current-guidance contradiction should be inferred without checking delivered instructions.'})
controls=json.loads((R.parent/'2026-10-04-numeric-absence-audit/sample.json').read_text());write('neutral-controls.json',[row for row in controls if (row['case'],row['answer']['question_id']) in [('nefigard','sq:missing:evidence-unbiased'),('canvas-program','sq:missing:evidence-unbiased')]])
# Official full PDF was retrieved from the current official download link, privately retained.
p=R.parents[3]/'diagnostics/attal-d3-assumptions-20261004/20190822-official-guidance.pdf';assert sha(p).upper()==_GUIDANCE_SOURCE_SHA256
write('official-provenance.json',{'retrieved_on':'2026-10-04','official_landing':'https://www.riskofbias.info/welcome/rob-2-0-tool/current-version-of-rob-2','official_download':'https://drive.google.com/uc?export=download&id=19R9savfPdCHC8XLz2iiMvL_71lPJERWK','private_pdf':str(p),'pdf_sha256':sha(p),'version':_GUIDANCE_VERSION,'matches_current_pack_source_sha256':True,'locators':['6.1.5–6.1.7, pp42–44','6.3, p44','Box8, SQ3.2–3.4, pp45–46'],'handbook':'https://www.cochrane.org/authors/handbooks-and-manuals/handbook/current/chapter-08','handbook_sections':['8.5.1','8.5.3'],'sas_primary_documentation':'https://support.sas.com/documentation/onlinedoc/stat/123/mi.pdf','sas_locator':'The MI Procedure, Statistical Assumptions for Multiple Imputation, printed p4745 (physical p35)','important_scope':'SAS documentation explains standard MI assumptions; trial-specific configuration/variables remain unreported, so no assertion that this exact documented procedure was used.'})
for p,h in proof['original_files'].items():assert sha(Path(p))==h
print('Exact target, actual method rows, mechanism/source-coverage evidence and historical delivery extracted; originals unchanged.')
