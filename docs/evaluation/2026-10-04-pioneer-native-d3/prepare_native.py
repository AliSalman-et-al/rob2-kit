from pathlib import Path
import hashlib,json,shutil,sqlite3,subprocess,tarfile
from rob2_kit.application.intake import prepare_batch_for_outcome,approve_review
from rob2_kit.application.evidence import list_sources,read_pages,select_text_evidence
from rob2_kit.application.proposal import save_proposal
from rob2_kit.application._state import _state
from rob2_kit.workflow_models import ProposalDraft
R=Path(__file__).resolve().parent;repo=Path('/home/ali/Documents/Codex/2026-10-02/task-4/rob2-kit');raw=Path('/home/ali/Documents/Code/rob2-kit-benchmark/rob2-meta-set-full-2026-09-29/trials/pioneer-6');w=R/'workspace';code=R/'code'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(n,x):(R/n).write_text(json.dumps(x,indent=2,ensure_ascii=False)+'\n')
assert not w.exists(),'Preserve prior staging; no rebuild'
code.mkdir();archive=R/'code.tar';subprocess.run(['git','archive','-o',str(archive),'HEAD'],cwd=repo,check=True)
with tarfile.open(archive) as t:t.extractall(code,filter='data')
source_inventory=json.loads((repo/'docs/evaluation/2026-10-04-stop-igan-d3-guidance/sources.json').read_text())['cases'][1]
input_dir=w/'input/pioneer-6';input_dir.mkdir(parents=True);roles=[];protected={source_inventory['bundle']:source_inventory['bundle_sha256']}
for item in source_inventory['sources']:
 s=item['source']
 if not item['raw_available']:continue
 p=raw/s['logical_path'];assert sha(p)==item['verified_raw_sha256'];shutil.copyfile(p,input_dir/p.name);protected[str(p)]=sha(p);protected[str(input_dir/p.name)]=sha(p);roles.append(f'{json.dumps(p.name)} = {json.dumps(s["role"])}')
(input_dir/'sources.toml').write_text('[roles]\n'+'\n'.join(roles)+'\n')
# No registry identifier/replay: unavailable original bytes are not replaced with a live capture.
prepared=prepare_batch_for_outcome(w,'Major adverse cardiovascular event (cardiovascular death, nonfatal MI, or nonfatal stroke)',0,['pioneer-6']);write('prepare-receipt.json',prepared)
sources=list_sources(w,'pioneer-6')['sources'];main=next(s for s in sources if s['logical_path']=='NEJMoa1901118.pdf')
selected=[]
for n in [1,2,3]:
 text=read_pages(w,'pioneer-6',main['id'],[n])['pages'][0]['text']
 selected.append(select_text_evidence(w,'pioneer-6',main['id'],n,text)['evidence']['handle'])
r=json.loads((R/'original-result.json').read_text());r={k:v for k,v in r.items() if k not in {'bindings','requested_outcome'}};r['evidence']=[{'kind':'narrative','handle':h} for h in selected];r['applicability']['evidence']=selected
saved=save_proposal(w,ProposalDraft.model_validate({'results':[r],'expected_revision':_state(w)['revision']}));write('proposal-receipt.json',saved)
assert saved['outcome']=='success',saved
s=_state(w);ack=approve_review(w,s['review']['identity'],caller='explicit-parent-task',method='previously-approved-exact-Result-reconstruction');write('approval-receipt.json',ack)
s=_state(w);assert not s.get('domain_records') and not s.get('working_checkpoints')
new_result=s['proposal']['payload']['results'][0]
for key in ['target','reported','relation']:
 assert new_result[key]==json.loads((R/'original-result.json').read_text())[key],key
write('source-provenance.json',{'original_inventory':source_inventory,'new_capture_sources':sources,'missing_registry':'Original bytes unavailable; registry not captured/replaced. Five original same-hash PDFs freshly ingested. Not exact archival replay.','postapproval_domain_records':0,'reconstructed_result':new_result,'source_target_review':'Exact first MACE treatment-policy/assignment hazard ratio0.79(CI.57–1.11), randomization through final follow-up. No on-treatment substitute. Main3/5/6; appendix14/15/17/19; final protocol follow-up and SAP definitions/primary analysis/sensitivity sections inspected. Article/S4 reports three sensitivities; SAP other sensitivities conditional on superiority. Full visual flow and S4 checked privately. No prior risk labels/answers copied.','source_availability_is_not_reading':True})
for p in (w/'.rob2-kit/sources').rglob('*'):
 if p.is_file():protected[str(p)]=sha(p)
for p in code.rglob('*'):
 if p.is_file():protected[str(p)]=sha(p)
write('protected-staging.json',protected)
shutil.copyfile(w/'.rob2-kit/canonical.sqlite3',R/'initial-canonical.sqlite3')
shutil.copytree(code/'src/rob2_kit/skills/rob2-assess',R/'rob2-assess')
print(json.dumps({'phase':s['phase'],'revision':s['revision'],'sources':len(sources),'prior_domain_records':0,'result':{k:new_result[k] for k in ['target','reported','relation']}}))
