from pathlib import Path
import json,hashlib,shutil
from rob2_kit.application._state import _state
from rob2_kit.application.evidence import list_sources
from rob2_kit.application.proposal import save_proposal
from rob2_kit.application.intake import approve_review
from rob2_kit.workflow_models import ProposalDraft
R=Path(__file__).resolve().parent;w=R/'workspace';code=R/'code';repo=Path('/home/ali/Documents/Codex/2026-10-02/task-4/rob2-kit')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(n,x):(R/n).write_text(json.dumps(x,indent=2,ensure_ascii=False)+'\n')
s=_state(w);assert s['phase']=='proposal' and s.get('review')
s=_state(w);ack=approve_review(w,s['review']['identity'],caller='explicit-parent-task',method='previously-approved-exact-Result-reconstruction');write('approval-receipt.json',ack)
s=_state(w);assert not s.get('domain_records');new_result=s['proposal']['payload']['results'][0]
original=json.loads((R/'original-result.json').read_text())
for key in ['target','reported','relation']:assert new_result[key]==original[key],(key,new_result[key],original[key])
inv=json.loads((repo/'docs/evaluation/2026-10-04-stop-igan-d3-guidance/sources.json').read_text())['cases'][1];sources=list_sources(w,'pioneer-6')['sources']
write('source-provenance.json',{'original_inventory':inv,'new_capture_sources':sources,'missing_registry':'Original registry bytes unavailable; no identifier/live replacement captured. Five original same-hash PDFs newly ingested; not exact archival replay.','postapproval_domain_records':0,'reconstructed_result':new_result,'source_target_review':'Exact first MACE assignment/treatment-policy hazard ratio0.79(CI.57–1.11), randomization through final follow-up. Main3/5/6; appendix14/15/17/19; SAP201–213, final-protocol follow-up sections reviewed. Three actual sensitivity analyses, plus planned conditional analyses distinguished. Flow/S4 pixels checked. No prior risk judgments copied.','source_availability_is_not_reading':True})
protected={inv['bundle']:inv['bundle_sha256']}
for x in inv['sources']:
 if x['raw_available']:
  raw=Path('/home/ali/Documents/Code/rob2-kit-benchmark/rob2-meta-set-full-2026-09-29/trials/pioneer-6')/x['source']['logical_path'];assert sha(raw)==x['verified_raw_sha256'];protected[str(raw)]=sha(raw)
for root in [w/'input',w/'.rob2-kit/sources',code]:
 for p in root.rglob('*'):
  if p.is_file():protected[str(p)]=sha(p)
write('protected-staging.json',protected);shutil.copyfile(w/'.rob2-kit/canonical.sqlite3',R/'initial-canonical.sqlite3');shutil.copytree(code/'src/rob2_kit/skills/rob2-assess',R/'rob2-assess')
print('Fresh assessment',s['revision'],'zero domains; exact scientific Result preserved')
