from pathlib import Path
import hashlib,json,shutil,subprocess
from rob2_kit.application._state import _state
from rob2_kit.application.intake import approve_review
from rob2_kit.application.evidence import list_sources,read_pages,select_text_evidence
from rob2_kit.application.proposal import save_proposal
from rob2_kit.workflow_models import ProposalDraft
R=Path(__file__).resolve().parent;w=R/'workspace';code=R/'code';repo=Path('/home/ali/Documents/Codex/2026-10-02/task-4/rob2-kit')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(n,x):(R/n).write_text(json.dumps(x,indent=2,ensure_ascii=False)+'\n')
sources=list_sources(w,'freeman-2020')['sources'];main=next(s for s in sources if s['logical_path']=='S2215-0366-20-30290-X.pdf');text=read_pages(w,'freeman-2020',main['id'],[7])['pages'][0]['text'];selected=select_text_evidence(w,'freeman-2020',main['id'],7,text)['evidence']['handle'];draft=json.loads((R/'reconstructed-proposal-input.json').read_text());draft['evidence'].append({'kind':'narrative','handle':selected});draft['applicability']['evidence'].append(selected);write('reconstructed-proposal-input.json',draft)
receipt=save_proposal(w,ProposalDraft.model_validate({'results':[draft],'expected_revision':_state(w)['revision']}));write('proposal-receipt.json',receipt);assert receipt['outcome']=='review_required',receipt
s=_state(w);write('approval-receipt.json',approve_review(w,s['review']['identity'],caller='explicit-parent-transfer-task',method='source-verified-exact-Result-reconstruction'))
s=_state(w);assert not s.get('domain_records') and not s.get('working_checkpoints');new=s['proposal']['payload']['results'][0];r=json.loads((R/'original-result.json').read_text())
for key in ['target','reported','relation']:assert new[key]==r[key],(key,new[key],r[key])
inv=json.loads((R/'original-source-inventory.json').read_text());write('source-provenance.json',{'original_inventory':inv,'new_capture_sources':sources,'missing_registry':'Original registry bytes absent; no live replacement or fabricated replay. Not exact archival replay.','reconstructed_result':new,'postapproval_domain_records':0,'operator_facts':'No domain answers or typed flow facts seeded. Only original scientific Result metadata and fresh source passages bound to proposal. Main7 actual complete quantitative anchor repaired offline page6 selection error.'})
protected={inv['bundle']:inv['bundle_sha256']}
raw=Path('/home/ali/Documents/Code/rob2-kit-benchmark/rob2-meta-set-full-2026-09-29/trials/freeman-2020')
for item in inv['sources']:
 if item['raw_available']:protected[str(raw/item['source']['logical_path'])]=item['verified_raw_sha256']
for root in [w/'input',w/'.rob2-kit/sources',code]:
 for p in root.rglob('*'):
  if p.is_file():protected[str(p)]=sha(p)
write('protected-staging.json',protected);shutil.copyfile(w/'.rob2-kit/canonical.sqlite3',R/'initial-canonical.sqlite3');shutil.copytree(code/'src/rob2_kit/skills/rob2-assess',R/'rob2-assess')
write('setup.json',{'workspace':str(w),'staging':str(R),'code':str(code),'skill':str(R/'rob2-assess/SKILL.md'),'python':'/home/ali/Documents/Codex/2026-10-02/task/rob2-kit/.venv/bin/python','code_sha':subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip(),'operator_reading':'preproposal only; zero postapproval domain facts; fresh mandatory reading epoch','credentials_read_or_copied':False})
print('Fresh native assessment, exact original target/reported/relation, zero domain facts:',s['revision'])
