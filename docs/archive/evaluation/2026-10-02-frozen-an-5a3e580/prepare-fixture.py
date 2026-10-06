import json,sqlite3,hashlib,shutil,subprocess
from pathlib import Path
from rob2_kit.application._state import _ensure,_state,_commit
from rob2_kit.application.domains import get_domain_context
sha=subprocess.check_output(['git','rev-parse','HEAD']).decode().strip();assert sha=='5a3e58034c57ef6c19a64fceeb3ced84edd30263';assert not subprocess.check_output(['git','status','--porcelain'])
root=Path('../diagnostics/frozen-an-5a3e580').resolve();root.mkdir()
out=Path('docs/evaluation/2026-10-02-frozen-an-5a3e580').resolve();out.mkdir()
limits={'wall_seconds':480,'idle_seconds':120,'tool_calls':16,'rejected_submissions':2,'input_tokens':400000,'uncached_input_tokens':100000,'output_tokens':5000}
for case,domain,prior in [('an-2021','domain:deviations','production-d2-an-2021')]:
 p=root/case;p.mkdir();w=p/'workspace';internal=w/'.rob2-kit';internal.mkdir(parents=True)
 source=Path('/home/ali/Documents/Code/rob2-kit-benchmark/benchmark-luna6-medium-2026-10-01/cases')/case/'.rob2-kit'
 dbhashes={}
 for name in ['canonical.sqlite3','derivative.sqlite3']:
  dbhashes[name]=hashlib.sha256((source/name).read_bytes()).hexdigest()
  with sqlite3.connect(f'file:{source/name}?mode=ro',uri=True) as a,sqlite3.connect(internal/name) as b:a.backup(b)
 _ensure(w);old=_state(w);state=json.loads(json.dumps(old));keep={'domain:randomization'}|({'domain:deviations'} if case=='monarch-plus' else set())
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
 context=get_domain_context(w,case,domain);assert context['outcome']=='success'
 home=p/'home';home.mkdir();oldroot=Path('../diagnostics')/prior
 for f in ['auth.json','models_cache.json']:shutil.copyfile(oldroot/'home'/f,home/f)
 config=(oldroot/'home/config.toml').read_text().replace(str(oldroot.resolve()),str(p));assert str(w) in config;assert 'model = "gpt-6-luna"' in config;assert 'model_reasoning_effort = "medium"' in config
 (home/'config.toml').write_text(config);shutil.copyfile(oldroot/'instructions.md',p/'instructions.md')
 prompt=(oldroot/'prompt.txt').read_text()
 if case=='an-2021':
  prompt=prompt.replace('One bounded attempt: at most 12 tool calls and 4 minutes. If submission is rejected or a budget is reached, stop and report the unresolved condition; no correction, retry or continuation.', 'One invocation: at most 16 tool calls, 8 minutes, 400000 total input tokens, 100000 uncached input tokens and 5000 output tokens. If a submission is rejected, you may correct your own draft once within these same bounds. Stop after two rejected submissions or the first budget reached; no further invocation, retry or continuation.')
 else:
  prompt=prompt.replace('Start with get_domain_context for domain:missing and complete its context pages.', 'Start with get_domain_context for domain:missing using max_response_bytes=80000 and complete its context pages.')
  prompt=prompt.replace('up to 18 tool calls and 8 minutes; if validation asks for a repair, one correction within that same budget is permitted.', 'up to 16 tool calls and 8 minutes, 400000 total input tokens, 100000 uncached input tokens and 5000 output tokens; if validation rejects a submission, one model-owned correction within that same budget is permitted. Stop after two rejected submissions or the first budget reached.')
 (p/'prompt.txt').write_text(prompt)
 manifest={'code_sha':sha,'model':'gpt-6-luna','reasoning_effort':'medium','cli_version':subprocess.check_output(['codex','--version']).decode().strip(),'case':case,'domain_id':domain,'guards':limits,'source_database_sha256':dbhashes,'restored_source_hash_verified':restored,'raw_sources_unavailable':missing,'approved_target':state['proposal']['payload']['results'][0]['target'],'reported_result':state['proposal']['payload']['results'][0]['reported'],'prior_scoped_fixture':str(oldroot.resolve()),'prior_retained_domains':sorted(keep),'initial_revision':state['revision'],'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),'qualification':'Known-case seeded repair check. Original Code approved Result and earlier Domain checkpoints retained; tested/later active Domain records, retrieval handles/deliveries and working notes cleared in this new copy. Historical canonical rows retained for integrity, no history/status tool exposed. Not an independent holdout, cold replay, full end-to-end benchmark or reference-label accuracy test. Prior labels are not supplied. Raw registry projection without original bytes remains unavailable, not replaced. Operator restored only exact hash-matched local raw Sources.','no_invocation_retry':True,'manual_repairs_during_run':False}
 (p/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');(p/'seed-state.json').write_text(json.dumps(state,indent=2)+'\n')
 q=out/case;q.mkdir()
 for f in ['manifest.json','prompt.txt','instructions.md']:shutil.copyfile(p/f,q/f)
 (q/'cli-config.toml').write_text(config)
 print(case,'restored',len(restored),'missing raw',len(missing),'model',manifest['model'],'preflight',context['outcome'])
(root/'artifact_directory.txt').write_text(str(out))
