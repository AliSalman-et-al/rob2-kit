from pathlib import Path
import json,sqlite3,tempfile,shutil,sys,hashlib
repo=Path.cwd();sys.path.insert(0,str(repo/'src'))
from rob2_kit.application._state import _state,_commit
from rob2_kit.application.trials import _review_domain_findings,review_trial
from rob2_kit.workflow_models import TrialReviewRequest
from rob2_kit.interfaces.mcp.contracts import normalize
from rob2_kit.interfaces.mcp.server import _project_review_trial
root=repo.parent/'diagnostics/frozen-bendix-d2-edf55fa/workspace';out=repo/'docs/evaluation/2026-10-03-bendix-review-visibility';out.mkdir(exist_ok=True)
before={n:hashlib.sha256((root/'.rob2-kit'/n).read_bytes()).hexdigest() for n in ['canonical.sqlite3','derivative.sqlite3']}
with tempfile.TemporaryDirectory() as tmp:
 copy=Path(tmp)/'workspace';shutil.copytree(root,copy);s=_state(copy)
 f=next(d for d in _review_domain_findings(copy,s,'bendix-1996') if d['domain_id']=='domain:deviations')
 (out/'exact-d2-review-projection.json').write_text(json.dumps(f,indent=2)+'\n')
 try:
  value={'outcome':'success','phase':'assessment','state_revision':s['revision'],'authoritative_wording':'Presentation fixture only; no Trial review or approval performed.','review':{'identity':'sha256:'+hashlib.sha256(b'visibility-fixture').hexdigest(),'trial_id':'bendix-1996','result_identity':s['domain_records']['bendix-1996:domain:deviations']['result_identity'],'checkpoint_ids':[f['checkpoint_identity']],'disposition':'assessed','reason':None},'domain_findings':[f],'retry':False}
  normalized=normalize('review_trial',value)
  summary=_project_review_trial(normalized,root=copy,cursor=None,selector=None,persist=True)
  (out/'public-review-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
  selected={}
  for q in ['sq:deviations:appropriate-analysis','sq:deviations:substantial-impact']:
   view=_project_review_trial(normalized,root=copy,cursor=None,selector={'domain_id':'domain:deviations','question_id':q},persist=True);pages=[view]
   while view['data']['review_page'].get('next_cursor'):
    view=_project_review_trial(normalized,root=copy,cursor=view['data']['review_page']['next_cursor'],selector=None,persist=True);pages.append(view)
   selected[q]=pages
  (out/'public-selected-review-pages.json').write_text(json.dumps(selected,indent=2)+'\n')
  print({q:[p['data']['review_page']['mode'] for p in ps] for q,ps in selected.items()})
 except Exception as error:
  (out/'public-projection-blocker.json').write_text(json.dumps({'error':type(error).__name__,'detail':str(error)},indent=2)+'\n');print(type(error).__name__,error)
assert all(hashlib.sha256((root/'.rob2-kit'/n).read_bytes()).hexdigest()==h for n,h in before.items())
(out/'provenance.json').write_text(json.dumps({'original_probe_database_sha256':before,'originals_unchanged':True,'fixture':'Exact accepted D2 application projection plus an explicitly synthetic transport header; no actual Trial review, assessment snapshot, inference or approval. '},indent=2)+'\n')
shutil.copyfile(Path(__file__),out/'audit-bendix-review-visibility.py')
