from pathlib import Path
import hashlib,json,shutil,subprocess,tarfile,sqlite3
from rob2_kit.application.intake import prepare_batch_for_outcome,approve_review
from rob2_kit.application.evidence import list_sources,read_pages,select_text_evidence
from rob2_kit.application.proposal import save_proposal
from rob2_kit.application._state import _state
from rob2_kit.workflow_models import ProposalDraft
from support.rob2 import _read_required_main_reports
R=Path(__file__).resolve().parent
repo=Path('/home/ali/Documents/Codex/2026-10-02/task-4/rob2-kit')
raw=Path('/home/ali/Documents/Code/rob2-kit-benchmark/rob2-meta-set-full-2026-09-29/trials/bagg-2022')
w=R/'workspace';code=R/'code';py='/home/ali/Documents/Codex/2026-10-02/task/rob2-kit/.venv/bin/python'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(n,x):(R/n).write_text(json.dumps(x,indent=2,ensure_ascii=False)+'\n')
assert not w.exists() and not code.exists(),'Preserve previous setup; no destructive rebuild'
assert not subprocess.check_output(['git','status','--porcelain'],cwd=repo,text=True).strip()
code.mkdir();archive=R/'code.tar';subprocess.run(['git','archive','-o',str(archive),'HEAD'],cwd=repo,check=True)
with tarfile.open(archive) as t:t.extractall(code,filter='data')
inv=json.loads((R/'original-source-inventory.json').read_text());r=json.loads((R/'original-result.json').read_text())
input_dir=w/'input/bagg-2022';input_dir.mkdir(parents=True);roles=[];protected={inv['bundle']:inv['bundle_sha256']}
for item in inv['sources']:
 s=item['source'];p=raw/s['logical_path'];assert sha(p)==s['sha256'].removeprefix('sha256:')
 shutil.copyfile(p,input_dir/p.name);roles.append(f'{json.dumps(p.name)} = {json.dumps(s["role"])}');protected[str(p)]=sha(p)
(input_dir/'sources.toml').write_text('[roles]\n'+'\n'.join(roles)+'\n')
write('prepare-receipt.json',prepare_batch_for_outcome(w,r['target']['outcome_definition'],0,['bagg-2022']))
_read_required_main_reports(w)
sources=list_sources(w,'bagg-2022')['sources'];main=next(x for x in sources if x['role']=='main_article');selected=[]
# Anchor only the approved quantitative Result, measurement/population and randomized design.
for n in [1,4,6]:
 text=read_pages(w,'bagg-2022',main['id'],[n])['pages'][0]['text'];selected.append(select_text_evidence(w,'bagg-2022',main['id'],n,text)['evidence']['handle'])
draft={k:v for k,v in r.items() if k not in {'bindings','requested_outcome'}}
draft['target']=dict(r['target'])
for k in ['outcome_definition','effect_of_interest','intended_analysis_population']:draft['target'].pop(k)
draft['target']['measurement']=dict(draft['target']['measurement']);draft['target']['measurement'].pop('metric');draft['target'].setdefault('baseline_subgroup',None)
draft['evidence']=[{'kind':'narrative','handle':h} for h in selected]
draft['applicability']=dict(draft['applicability']);draft['applicability']['evidence']=selected
write('reconstructed-proposal-input.json',draft)
receipt=save_proposal(w,ProposalDraft.model_validate({'results':[draft],'expected_revision':_state(w)['revision']}));write('proposal-receipt.json',receipt);assert receipt['outcome']=='review_required',receipt
state=_state(w);write('approval-receipt.json',approve_review(w,state['review']['identity'],caller='explicit-parent-integrated-D5-task',method='verified-original-source-exact-Result-reconstruction'))
state=_state(w);assert not state.get('domain_records')
new=state['proposal']['payload']['results'][0]
for key in ['target','reported','relation']:assert new[key]==r[key],(key,new[key],r[key])
with sqlite3.connect(w/'.rob2-kit/working.sqlite3') as db:assert db.execute('SELECT COUNT(*) FROM working_checkpoints').fetchone()[0]==0
with sqlite3.connect(w/'.rob2-kit/derivative.sqlite3') as db:assert db.execute("SELECT COUNT(*) FROM page_reads WHERE phase='assessment'").fetchone()[0]==0
write('source-provenance.json',{'original_inventory':inv,'new_capture_sources':sources,'reconstructed_result':new,'postapproval_domain_records':0,'operator_facts':'No working observations, scoped notes, participant-flow rows, archived domain answers or gold seeded. Exact approved scientific target/report/relation reconstructed from verified original PDFs. All original registered source bytes available.'})
subprocess.run([py,'-m','rob2_kit.interfaces.cli.app','export-skill','--output',str(R/'rob2-assess')],cwd=repo,check=True)
for p in (R/'rob2-assess').rglob('*'):
 if p.is_file():assert sha(p)==sha(repo/'src/rob2_kit/skills/rob2-assess'/p.relative_to(R/'rob2-assess'))
for root in [w/'input',w/'.rob2-kit/sources',code,R/'rob2-assess']:
 for p in root.rglob('*'):
  if p.is_file():protected[str(p)]=sha(p)
write('protected-staging.json',protected);shutil.copyfile(w/'.rob2-kit/canonical.sqlite3',R/'initial-canonical.sqlite3')
write('setup.json',{'workspace':str(w),'staging':str(R),'code':str(code),'skill':str(R/'rob2-assess/SKILL.md'),'python':py,'code_sha':subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip(),'operator_reading':'Preproposal only; no assessment-epoch source reads or seeded facts','exported_skill_verified':True,'credentials_read_or_copied':False})
print('Prepared exact original Result; zero scoped/working observations or postapproval reading:',state['revision'])
