from pathlib import Path
import sys,json,sqlite3,hashlib,shutil,subprocess
repo=Path('/home/ali/Documents/Codex/2026-10-02/task-4/rob2-kit')
sys.path.insert(0,str(repo/'src'));sys.path.insert(0,str(repo/'scripts'))
from rob2_kit.application._state import _ensure,_state,_commit
from rob2_kit.application.domains import get_domain_context
from domain_probe_controls import write_controls
sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()
assert sha.startswith('96ffe34')
assert not subprocess.check_output(['git','status','--porcelain'],cwd=repo)
assert not subprocess.check_output(['git','diff','55c2d04',sha,'--','src'],cwd=repo)
case='award-1-2014'
inventory=json.loads((repo.parent/'diagnostics/paid-case-inventory.json').read_text())
assert case not in inventory['excluded_development_cases']
root=repo.parent/'diagnostics/frozen-award1-d3-repair4';root.mkdir()
w=root/'workspace';internal=w/'.rob2-kit';internal.mkdir(parents=True)
source=Path('/home/ali/Documents/Code/rob2-kit-benchmark/benchmark-luna6-medium-2026-10-01/cases')/case/'.rob2-kit'
hashes={}
for name in ['canonical.sqlite3','derivative.sqlite3']:
 hashes[name]=hashlib.sha256((source/name).read_bytes()).hexdigest()
 with sqlite3.connect(f'file:{source/name}?mode=ro',uri=True) as a,sqlite3.connect(internal/name) as b:a.backup(b)
_ensure(w);old=_state(w);state=json.loads(json.dumps(old));keep={'domain:randomization','domain:deviations'}
state['domain_records']={k:v for k,v in state['domain_records'].items() if v['domain_id'] in keep}
for name in ['domain_history','domain_history_records']:state[name]={k:v for k,v in state[name].items() if any(k.endswith(':'+d) for d in keep)}
for name in ['snapshot_history','snapshot_history_records','snapshots','reasoning_records','trial_closures','trial_reviews','terminals']:state[name]={}
state.update(review=None,artifact=None,phase='assessment',trial_dispositions={case:'pending'},domain_index={case:[]})
state=_commit(w,state,old['revision'])
with sqlite3.connect(internal/'derivative.sqlite3') as c:
 for table in ['renders','visual_deliveries','evidence_handles','search_receipts','search_sessions','search_candidates','search_domain_associations','search_evidence_provenance','search_evidence_provenance_history','page_reads','domain_context_delivery','domain_context_views']:c.execute('DELETE FROM '+table)
restored=[];missing=[];corpus=Path('/home/ali/Documents/Code/rob2-kit-benchmark/rob2-meta-set-full-2026-09-29/trials')/case
for s in state['batch']['trials'][0]['sources']:
 src=corpus/s['logical_path'];dest=internal/'sources'/case/(s['id']+'.bin')
 if not src.exists():missing.append(s);continue
 raw=src.read_bytes();assert 'sha256:'+hashlib.sha256(raw).hexdigest()==s['sha256'];dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(raw);restored.append(s)
context=get_domain_context(w,case,'domain:missing');assert context['outcome']=='success',context
(root/'preflight-context.json').write_text(json.dumps(context,indent=2)+'\n')
home=root/'home';home.mkdir();prior=repo.parent/'diagnostics/frozen-deliver-d3-9497c9f'
for f in ['auth.json','models_cache.json']:shutil.copyfile(prior/'home'/f,home/f)
config=(prior/'home/config.toml').read_text().replace(str(prior),str(root))
assert 'model = "gpt-6-luna"' in config and 'model_reasoning_effort = "medium"' in config
(home/'config.toml').write_text(config);shutil.copyfile(prior/'instructions.md',root/'instructions.md')
prompt='Assess only Domain 3 for award-1-2014 using its existing approved Result and current production guidance. Start with get_domain_context for domain:missing and complete all returned context pages. Read the required captured main report and relevant captured source evidence, preserving the exact approved groups, outcome, assignment effect, analysis and timing. Local PDFs are restored with matching hashes. A historical registry projection lacks its retained raw bytes; retain that limitation and do not capture a replacement or access the network. Submit the complete active answer path through save_domain_judgment and use its server-computed judgment. Retain material unknowns and substantive counterpoints. Stop after D3; do not assess other Domains, finalize, use outside knowledge or perform coding. Return a concise account of scientific warrants, accepted checkpoint or failure (400 words or less).'
manifest={'code_sha':sha,'scientific_implementation_sha':'55c2d042cdd2c5a2956ecc8478c859dfaac152d0','model':'gpt-6-luna','reasoning_effort':'medium','cli_version':subprocess.check_output(['codex','--version'],text=True).strip(),'case':case,'domain_id':'domain:missing','source_database_sha256':hashes,'restored_source_hash_verified':restored,'raw_sources_unavailable':missing,'approved_target':state['proposal']['payload']['results'][0]['target'],'reported_result':state['proposal']['payload']['results'][0]['reported'],'prior_retained_domains':sorted(keep),'initial_revision':state['revision'],'selection_hypothesis':'Operator-only: continuous HbA1c result with LOCF and post-rescue exclusion. Distinguish observed from analyzed/imputed values and appraise exact handling, without selecting an answer from an ITT denominator. Selected from source evidence and availability, not human labels. No count/page/answer hint to model.','unused_development_case_inventory':'paid-case-inventory.json','qualification':'Original Oct1 Code approved Result retained; D1/D2 retained for sequence; D3/later active records and derivative delivery removed only in new copy. Not cold full-trial assessment or held-out validation. Registry raw unavailable; human target alignment provisional.','no_invocation_retry':True,'manual_repairs_during_run':False,'guard_change_authorization':'Parent explicitly adopts four total saves and two consecutive identical rejections, with retained 800k total/100k uncached/5k output/20 tools/480s wall/120s idle.'}
write_controls(root,manifest,prompt)
(root/'seed-state.json').write_text(json.dumps(state,indent=2)+'\n')
shutil.copyfile(repo.parent/'diagnostics/paid-case-inventory.json',root/'paid-case-inventory.json')
for name in hashes:assert hashlib.sha256((source/name).read_bytes()).hexdigest()==hashes[name]
print('Prepared',case,'restored',len(restored),'unavailable',len(missing),'model',manifest['model'],manifest['reasoning_effort'])
