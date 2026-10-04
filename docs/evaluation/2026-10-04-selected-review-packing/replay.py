"""Pure before/after bounded projection replay on preserved scientific snapshots."""
from pathlib import Path
import json,sys,types
from rob2_kit.interfaces.mcp import server
R=Path(__file__).resolve().parent
arm=sys.argv[1];assert arm in ['before','after']
server.uuid.uuid4=lambda:types.SimpleNamespace(hex='7a858b92269645099fa385326e280489')
rows=[]
for case,domain in [('baby','domain:measurement'),('exscel','domain:selection')]:
 snapshot=json.loads((R/f'{case}-snapshot.json').read_text());original=json.dumps(snapshot,sort_keys=True)
 selector={'domain_id':domain};kind,target=server._review_target(snapshot,selector)
 digest=server._review_view_digest(snapshot,selector)
 response=server._project_review_trial(snapshot,cursor=None,selector=selector,root=R,persist=False)
 (R/f'{case}-{arm}-first-view.json').write_text(json.dumps(response,ensure_ascii=False,indent=2)+'\n')
 page=response['data']['review_page'];first_text=page.get('fragment') or json.dumps(response['data'],ensure_ascii=False)
 expected={a['question_id']:a for a in target['answers']};shown={a['question_id']:a for d in response['data'].get('domain_findings',[]) for a in d['answers']}
 fields=['question_id','question','answer','driver','warrant','justification','unknowns','counterevidence','limitations','conflicts','uninvestigated_routes','missing_data','evidence','bases']
 complete_claims=bool(shown) and all(all(shown[q].get(k)==a.get(k) for k in fields) for q,a in expected.items())
 raw=json.dumps(target,ensure_ascii=False,sort_keys=True,separators=(',',':'))
 parts=[];offset=0;lengths=[]
 while offset<len(raw):
  part=server._review_fragment_response(snapshot,snapshot,selector,digest,'7a858b92269645099fa385326e280489',offset)
  p=part['data']['review_page'];assert server._review_transport_bytes(part)<=24000
  assert p['offset']==offset;parts.append(p['fragment']);offset+=len(parts[-1]);lengths.append(len(parts[-1]))
 assert ''.join(parts)==raw and json.loads(raw)==target
 assert json.dumps(snapshot,sort_keys=True)==original
 row={'case':case,'mode':page['mode'],'complete':page['complete'],'first_view_bytes':server._review_transport_bytes(response),'all_saved_claim_fields_exact_in_first_view':complete_claims,'source_expansion_original_fields_preserved':all(all(all(expansion.get(k)==value for k,value in old.items() if k!='windows') and all(all(window.get(k)==value for k,value in old_window.items()) for window,old_window in zip(expansion.get('windows',[]),old.get('windows',[]),strict=True)) for expansion,old in zip(shown[q].get('evidence_expansions',[]),answer.get('evidence_expansions',[]),strict=True)) for q,answer in expected.items()) if shown else False,'answer_count':len(expected),'question_ids_visible':[q for q in expected if q in first_text],'count_clause_visible':'13/86' in first_text,'snapshot_digest':page['snapshot_digest'],'selector':page.get('selector'),'target':page.get('target'),'stable_recovery':page.get('stable_recovery'),'deferred_fields':page.get('deferred_fields'),'full_fragment_lengths':lengths,'full_target_characters':len(raw),'full_recovery_exact':True,'snapshot_unchanged':True}
 rows.append(row)
(R/f'{arm}-replay.json').write_text(json.dumps(rows,indent=2)+'\n')
print(json.dumps(rows,indent=2))
