"""Offline scientific-section demonstration from frozen Code bundles and source pages.

Uses the same question assembler and prototype projection as native MCP delivery.
Does not fabricate pruned source blobs or bypass the live source-integrity verifier.
"""
from __future__ import annotations
import hashlib,json,copy,zipfile,subprocess
from pathlib import Path
from rob2_kit.application.domains import (
 _apply_authoritative_d3_guidance,_domain_question_cards,_official_guidance_recovery,
 _comparison_cards,_DOMAIN_GUIDANCE,_DOMAIN_TRAPS,_RESPONSE_FRAMEWORK,
)
from rob2_kit.packs import SCIENTIFIC_PACK
from scripts.verify_bundle import verify

R=Path(__file__).resolve().parent
PREVIOUS=R.parent/'2026-10-04-attal-d3-assumptions'

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(name,x):(R/name).write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def sections(canonical,case,domain,pages):
 result=canonical['proposal']['payload']['results'][0]
 source_inventory=canonical['batch']['trials'][0]['sources']
 record=canonical['domain_records'][case+':'+domain]
 evidence=canonical['proposal']['evidence']
 return {'trial_id':case,'domain_id':domain,'pack':{'id':SCIENTIFIC_PACK.id,'version':SCIENTIFIC_PACK.version,'content_hash':SCIENTIFIC_PACK.content_hash},'result':result,'evidence':evidence,'answers':record['answers'],'source_inventory':source_inventory,'frozen_source_pages':pages,'questions':_domain_question_cards(domain,set(record['active_questions']),record['identity']),'official_guidance':_official_guidance_recovery(domain),'response_framework':_RESPONSE_FRAMEWORK.model_dump(mode='json'),'guidance':['Answer every activated question using the approved Result.',*_DOMAIN_GUIDANCE],'traps':['A no-hit search describes one lexical query, not scientific absence.',*_DOMAIN_TRAPS],'comparison_cards':_comparison_cards(domain,result,evidence,record['answers'],source_inventory)}

def main():
 previous=json.loads((PREVIOUS/'manifest.json').read_text());protected=previous['protected_originals']
 for p,h in protected.items():assert sha(Path(p))==h
 cases=json.loads((PREVIOUS/'sources.json').read_text())['cases'];proof=json.loads((PREVIOUS/'provenance.json').read_text());controls=json.loads((PREVIOUS/'neutral-controls.json').read_text())
 bundles={'attal-2016':proof['bundle'],'nefigard':next(x['bundle'] for x in controls if x['case']=='nefigard')}
 results=[];inventory=[]
 for case,bundle in bundles.items():
  valid,detail=verify(Path(bundle));assert valid,detail
  with zipfile.ZipFile(bundle) as z:canonical=json.loads(z.read('canonical.json'))
  pages=next(c['pages'] for c in cases if c['case']==case)
  before=sections(canonical,case,'domain:missing',pages);after=copy.deepcopy(before);_apply_authoritative_d3_guidance(after)
  for arm,context in [('current',before),('prototype',after)]:write(case+'-'+arm+'-scientific-sections.json',context)
  for key in ('result','evidence','answers','source_inventory','frozen_source_pages'):
   assert before[key]==after[key],key
  removed=[]
  for old,new in zip(before['questions'],after['questions'],strict=True):
   for key in ('bias_construct','decision_rule','evidence_needed','no_information_rule','answer_anchors','considerations','invalid_shortcuts'):
    value=old[key];items=list(value) if isinstance(value,tuple) else [value]
    for i,item in enumerate(items):removed.append({'question_id':old['id'],'field':key,'index':i,'removed_statement':item})
   assert all(old[key]==new[key] for key in ('id','wording','options','activation','activation_status','query_suggestions'))
  inventory=removed
  scientific_keys=('questions','official_guidance','response_framework','guidance','traps','comparison_cards')
  size=lambda c:len(json.dumps({k:c[k] for k in scientific_keys},ensure_ascii=False,separators=(',',':')).encode())
  results.append({'case':case,'current_scientific_bytes':size(before),'prototype_scientific_bytes':size(after),'delta_bytes':size(after)-size(before),'official_current_words':sum(len(s['excerpt'].split()) for s in before['official_guidance']['sections']),'official_prototype_words':sum(len(s['excerpt'].split()) for s in after['official_guidance']['sections']),'removed_question_rule_fields':7*len(before['questions']),'removed_statement_items':len(removed),'preserved_scientific_data':True,'model_calls':0})
  for domain in ('domain:deviations','domain:selection'):
   a=sections(canonical,case,domain,pages);b=copy.deepcopy(a);assert a==b
 for p,h in protected.items():assert sha(Path(p))==h
 write('removed-question-statements.json',inventory)
 skill_paths=['src/rob2_kit/skills/rob2-assess/SKILL.md','src/rob2_kit/skills/rob2-assess/references/missing.md','src/rob2_kit/skills/rob2-assess/references/evidence.md']
 write('skill-before-after.json',{p:{'before':subprocess.check_output(['git','show','f548c03:'+p],text=True),'after':Path(p).read_text()} for p in skill_paths})
 write('context-comparison.json',{'canonical_pack':before['pack'],'cases':results,'unchanged_controls':['D2 native neutral context','D5 native neutral context'],'protected_original_hashes_unchanged':True,'historical_bundles_verified':True,'model_calls':0,'prototype_only':True,'demonstration_scope':'Scientific sections assembled using production helpers and frozen source pages. Not a live MCP replay: Code cases have pruned .rob2-kit/sources blobs. Live integrity verification was not bypassed; failed disposable replay copies remain private. Native MCP behavior is tested separately on an intact neutral workspace.','caveat':'Archived answers retained for provenance. Future matched model input must omit saved judgments/warrants and reference labels.'})
 print(json.dumps(results,indent=2))
if __name__=='__main__':main()
