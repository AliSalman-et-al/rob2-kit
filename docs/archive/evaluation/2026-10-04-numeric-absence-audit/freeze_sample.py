"""Read only named Code benchmark/finalized artifacts; freeze before lexical results."""
from __future__ import annotations
import hashlib,json,zipfile
from pathlib import Path
from scripts.verify_bundle import verify
from rob2_kit.application.source_handles import source_handle
R=Path(__file__).resolve().parent
B=Path('/home/ali/Documents/Code/rob2-kit-benchmark/benchmark-luna6-medium-2026-10-01/cases')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def freeze(bundle,case,question,role,stress):
 valid,message=verify(bundle)
 assert valid,(case,message)
 with zipfile.ZipFile(bundle) as z:
  c=json.loads(z.read('canonical.json'))
  d=next(d for d in c['domain_records'].values() if any(a['question_id']==question for a in d['answers']))
  a=next(a for a in d['answers'] if a['question_id']==question)
  selected=[]
  for basis in a['bases']:
   identity=basis.get('evidence')
   if not identity:continue
   e=json.loads(z.read('evidence/'+identity.split(':')[1]+'.json'))
   assert e['kind'] in {'narrative','figure'}
   recovery=({'operation':'read_pages','arguments':{'trial_id':d['trial_id'],'windows':[{'source_id':source_handle(e['source_id']),'page':e['page'],'start_line':e['start_line'],'end_line':e['end_line']}]}} if e['kind']=='narrative' else {'operation':'render_page','arguments':{'trial_id':d['trial_id'],'source_id':source_handle(e['source_id']),'page':e['render']['page']}})
   selected.append({'role':basis['kind'],'evidence':e,'recovery':recovery})
 return {'case':case,'sample_role':role,'stress':stress,'bundle':str(bundle),'bundle_sha256':sha(bundle),'domain_id':d['domain_id'],'trial_id':d['trial_id'],'checkpoint_identity':d['identity'],'answer':a,'selected':selected,'source_inventory':next(t['sources'] for t in c['batch']['trials'] if t['id']==d['trial_id'])}
def main():
 assert not (R/'sample.json').exists(),'Preserve frozen sample'
 p=json.loads((R/'protocol.json').read_text());rows=[]
 baby=R.parent/'2026-10-04-gupta-fork-continuation/caf5f259a9f5eef456a05a6543fac933aa9bcbc55a99ba4b03430da8b760ab2d.rob2.zip'
 rows.append(freeze(baby,'gupta-2024','sq:measurement:differential','known_gap','correct count with unrelated selected citations'))
 for s in p['controls']:
  paths=list((B/s['case']/'.rob2-kit/finalized').glob('*.zip'));assert len(paths)==1,(s['case'],paths)
  rows.append(freeze(paths[0],s['case'],s['question'],'control',s['stress']))
 (R/'sample.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 (R/'freeze.json').write_text(json.dumps({'protocol_sha256':sha(R/'protocol.json'),'sample_sha256':sha(R/'sample.json'),'algorithm_sha256':sha(R/'audit.py'),'bundles':{r['bundle']:r['bundle_sha256'] for r in rows},'model_calls':0,'basis_evidence_verification':'independent bundle verifier passed all selected immutable archives'},indent=2)+'\n')
 print(f'Frozen {len(rows)} answers, {len({r["case"] for r in rows})} cases; all bundle verifiers passed.')
if __name__=='__main__':main()
