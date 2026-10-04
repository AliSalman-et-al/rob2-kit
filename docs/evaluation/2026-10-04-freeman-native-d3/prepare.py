from pathlib import Path
import hashlib,json,shutil,subprocess,tarfile,zipfile
from rob2_kit.application.intake import prepare_batch_for_outcome,approve_review
from rob2_kit.application.evidence import list_sources,read_pages,select_text_evidence
from rob2_kit.application.proposal import save_proposal
from rob2_kit.application._state import _state
from rob2_kit.workflow_models import ProposalDraft
from support.rob2 import _read_required_main_reports
R=Path(__file__).resolve().parent;repo=Path('/home/ali/Documents/Codex/2026-10-02/task-4/rob2-kit');raw=Path('/home/ali/Documents/Code/rob2-kit-benchmark/rob2-meta-set-full-2026-09-29/trials/freeman-2020');w=R/'workspace';code=R/'code'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(n,x):(R/n).write_text(json.dumps(x,indent=2,ensure_ascii=False)+'\n')
assert not w.exists(),'No destructive rebuild'
code.mkdir();archive=R/'code.tar';subprocess.run(['git','archive','-o',str(archive),'HEAD'],cwd=repo,check=True)
with tarfile.open(archive) as t:t.extractall(code,filter='data')
bundle=next(Path('/home/ali/Documents/Code/rob2-kit-benchmark/benchmark-luna6-medium-2026-10-01/cases/freeman-2020/.rob2-kit/finalized').glob('*.zip'))
with zipfile.ZipFile(bundle) as z:c=json.loads(z.read('canonical.json'));inventory=c['batch']['trials'][0]['sources']
input_dir=w/'input/freeman-2020';input_dir.mkdir(parents=True);roles=[];protected={str(bundle):sha(bundle)};inv=[]
for s in inventory:
 p=raw/s['logical_path'];available=p.is_file();item={'source':s,'raw_available':available}
 if available:
  assert sha(p)==s['sha256'].removeprefix('sha256:');item['verified_raw_sha256']=sha(p);shutil.copyfile(p,input_dir/p.name);protected[str(p)]=sha(p);protected[str(input_dir/p.name)]=sha(p);roles.append(f'{json.dumps(p.name)} = {json.dumps(s["role"])}')
 inv.append(item)
write('original-source-inventory.json',{'case':'freeman-2020','bundle':str(bundle),'bundle_sha256':sha(bundle),'sources':inv,'selection':'Source-complete primary+appendix+author manuscript; continuous repeated urine outcome with Bayesian MI in small adaptive parallel trial; not selected by labels. No dedicated improvement-campaign transfer identified, original Oct1 baseline exposure disclosed.'})
(input_dir/'sources.toml').write_text('[roles]\n'+'\n'.join(roles)+'\n')
r=json.loads((R/'original-result.json').read_text());requested=r['target']['outcome_definition']
write('prepare-receipt.json',prepare_batch_for_outcome(w,requested,0,['freeman-2020']))
# Only supported preproposal main reading; approval starts a new reading epoch.
_read_required_main_reports(w)
sources=list_sources(w,'freeman-2020')['sources'];main=next(s for s in sources if s['logical_path']=='S2215-0366-20-30290-X.pdf');selected=[]
for n in [1,3,6]:
 text=read_pages(w,'freeman-2020',main['id'],[n])['pages'][0]['text'];selected.append(select_text_evidence(w,'freeman-2020',main['id'],n,text)['evidence']['handle'])
draft={k:v for k,v in r.items() if k not in {'bindings','requested_outcome'}};draft['target']=dict(r['target']);draft['target'].pop('outcome_definition');draft['target'].pop('effect_of_interest');draft['target'].pop('intended_analysis_population');draft['target']['measurement']=dict(draft['target']['measurement']);draft['target']['measurement'].pop('metric');draft['target'].setdefault('baseline_subgroup',None);draft['evidence']=[{'kind':'narrative','handle':h} for h in selected];draft['applicability']=dict(draft['applicability']);draft['applicability']['evidence']=selected
write('reconstructed-proposal-input.json',draft)
receipt=save_proposal(w,ProposalDraft.model_validate({'results':[draft],'expected_revision':_state(w)['revision']}));write('proposal-receipt.json',receipt);assert receipt['outcome']=='review_required',receipt
s=_state(w);write('approval-receipt.json',approve_review(w,s['review']['identity'],caller='explicit-parent-transfer-task',method='source-verified-exact-Result-reconstruction'))
s=_state(w);assert not s.get('domain_records') and not s.get('working_checkpoints');new=s['proposal']['payload']['results'][0]
for key in ['target','reported','relation']:assert new[key]==r[key],(key,new[key],r[key])
write('source-provenance.json',{'original_inventory':json.loads((R/'original-source-inventory.json').read_text()),'new_capture_sources':sources,'missing_registry':'Original registry bytes absent; no live replacement or fabricated replay. Not exact archival replay.','reconstructed_result':new,'postapproval_domain_records':0,'operator_facts':'No domain answers or typed flow facts seeded. Only original scientific Result metadata and fresh source passages bound to proposal.'})
for root in [w/'input',w/'.rob2-kit/sources',code]:
 for p in root.rglob('*'):
  if p.is_file():protected[str(p)]=sha(p)
write('protected-staging.json',protected);shutil.copyfile(w/'.rob2-kit/canonical.sqlite3',R/'initial-canonical.sqlite3');shutil.copytree(code/'src/rob2_kit/skills/rob2-assess',R/'rob2-assess')
write('setup.json',{'workspace':str(w),'staging':str(R),'code':str(code),'skill':str(R/'rob2-assess/SKILL.md'),'python':'/home/ali/Documents/Codex/2026-10-02/task/rob2-kit/.venv/bin/python','code_sha':subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip(),'operator_reading':'preproposal only; zero postapproval domain facts; fresh mandatory reading epoch','credentials_read_or_copied':False})
print('Fresh native assessment, exact original target/reported/relation, zero domain facts:',s['revision'])
