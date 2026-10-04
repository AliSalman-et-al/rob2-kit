"""Offline follow-up of frozen native records; no model/source delivery calls."""
from pathlib import Path
import hashlib,json,sqlite3
from rob2_kit.application.domains import _comparison_cards
from rob2_kit.interfaces.mcp.contracts import ParticipantFlowProjection
R=Path(__file__).resolve().parent
P=Path(json.loads((R/'setup.json').read_text())['staging'])
def write(n,x):(R/n).write_text(json.dumps(x,indent=2,ensure_ascii=False)+'\n')
receipts=json.loads((R/'native-receipts.json').read_text());saved=json.loads((R/'saved-d3.json').read_text())
submission=next(x for x in receipts if x['tool']=='save_domain_judgment')['arguments']
selected=[x['receipt']['data']['evidence'] for x in receipts if x['tool'] in {'select_text_evidence','select_visual_evidence'}]
catalog={e['identity']:e for e in selected};rowdata=saved['answers'][0]['missing_data']
card=_comparison_cards('domain:missing',{},catalog,[],[],participant_flow_data=rowdata)[0]
projected=[ParticipantFlowProjection.model_validate(r).model_dump(mode='json') for r in card['participant_flow']]
figures=[e for e in selected if e['kind']=='figure'];assert len(figures)==1
assert all(r['figures'][0]['handle']==figures[0]['handle'] for r in projected)
assert all(r['figures'][0]['provenance']=='host_visual' for r in projected)
assert all(r['value'] is None for r in projected if r['kind']=='observed')
old=next(x for x in receipts if x['item']=='item_19')['receipt']['data']['comparison_cards'][0]['participant_flow']
assert all(not r.get('figures') for r in old)
write('visual-projection-review.json',{'scope':'offline projection only; not behavioral improvement or model rerun','old_visual_basis_missing':True,'new_visual_basis_present':True,'unknown_observed_unchanged':True,'projected_flow':projected})
with sqlite3.connect(f'file:{P}/workspace/.rob2-kit/derivative.sqlite3?mode=ro',uri=True) as c:
 unread=[]
 for source,page in [('source_6532547b9f9ff7eda508180f83872c59c6dfb6509815a65c2a2b8b86c6b21d6a',p) for p in [203,204,205,206,207,208]]+ [('source_3948b22b5f4feb6248896515ee9183abbaee3acb930dcf293aec83e07c1962cd',19)]:
  text=c.execute('SELECT text FROM pages WHERE source_id=? AND page=?',(source,page)).fetchone()[0]
  unread.append({'source_id':source,'physical_page':page,'start_line':1,'end_line':len(text.splitlines()),'numbered_text':'\n'.join(f'{n}|{line}' for n,line in enumerate(text.splitlines(),1)),'delivered_to_model':False})
first=next(x for x in receipts if x['item']=='item_2')['receipt']['data']
write('warrant-review.json',{'original_submission':submission,'supporting_selected_evidence':selected,'unread_relevant_captured_text':unread,'actual_model_guidance':{'guidance_profile':first['guidance_profile'],'completion_rule':first['completion_rule'],'official_guidance':first['official_guidance'],'prompt':(R/'prompt.txt').read_text()},'S4_visual_review':{'private_image':str(P/'appendix-p19.png'),'sha256':hashlib.sha256((P/'appendix-p19.png').read_bytes()).hexdigest(),'performed_results':[{'analysis':'confirmatory','HR':'.79','CI':'.57–1.11','events_analyzed':['61/1591','76/1592']},{'analysis':'additional covariates','HR':'.77','CI':'.55–1.08','events_analyzed':['61/1584','76/1579']},{'analysis':'on treatment38days','HR':'.82','CI':'.58–1.17','events_analyzed':['57/1591','71/1591']},{'analysis':'on treatment7days','HR':'.79','CI':'.54–1.14','events_analyzed':['49/1591','64/1591']}],'delivered_to_model':False}})
print('Frozen case visual-basis loss reproduced and corrected offline; original saved rows unchanged.')
