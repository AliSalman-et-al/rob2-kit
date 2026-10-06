import json, hashlib, shutil, subprocess
from pathlib import Path
from rob2_kit.application._state import _state
from rob2_kit.application.domains import get_domain_context
root=Path('diagnostics/frozen-deliver-d3-9c7ba8c').resolve();w=root/'workspace';state=_state(w)
sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd='rob2-kit',text=True).strip();keep={'domain:randomization','domain:deviations'}
source=Path('/home/ali/Documents/Code/rob2-kit-benchmark/benchmark-luna6-medium-2026-10-01/cases/deliver/.rob2-kit')
hashes={n:hashlib.sha256((source/n).read_bytes()).hexdigest() for n in ['canonical.sqlite3','derivative.sqlite3']}
restored=[];missing=[]
for s in state['batch']['trials'][0]['sources']:
 dest=w/'.rob2-kit/sources/deliver'/(s['id']+'.bin')
 (restored if dest.exists() else missing).append(s)
context=get_domain_context(w,'deliver','domain:missing');assert context['outcome']=='success',context
(root/'preflight-context.json').write_text(json.dumps(context,indent=2)+'\n')
home=root/'home';home.mkdir();prior=Path('diagnostics/frozen-an-5a3e580/an-2021').resolve()
for f in ['auth.json','models_cache.json']:shutil.copyfile(prior/'home'/f,home/f)
config=(prior/'home/config.toml').read_text().replace(str(prior),str(root))
config=config.replace('"search_sources",','"search_sources", "search_sources_batch", "list_sources",')
assert 'model = "gpt-6-luna"' in config and 'model_reasoning_effort = "medium"' in config
(home/'config.toml').write_text(config);shutil.copyfile(prior/'instructions.md',root/'instructions.md')
prompt='''Assess only Domain 3 for deliver using its existing approved Result and current production guidance. Start with get_domain_context for domain:missing using max_response_bytes=80000 and complete its context pages. Read the required captured main report and relevant captured source evidence, preserving the exact approved groups, primary composite, assignment effect, analysis and timing. Main article and local PDFs are restored with matching hashes. A historical registry projection lacks its retained raw bytes, so a read may be unavailable; retain that limitation and do not capture a replacement or access the network. Submit the complete active answer path once via save_domain_judgment and use its server-computed judgment. Retain material unknowns and substantive counterpoints. Stop after D3; do not assess other Domains, finalize, use outside knowledge or perform coding. One invocation only: at most 12 tool calls, 4 minutes, 300000 total input tokens, 60000 uncached input tokens and 4000 output tokens. Stop immediately after the first save result, accepted or rejected, or first budget reached. No correction, retry or continuation. Return a concise account of scientific warrants, accepted checkpoint or failure (400 words or less).'''
(root/'prompt.txt').write_text(prompt)
limits={'wall_seconds':240,'idle_seconds':90,'tool_calls':12,'rejected_submissions':1,'input_tokens':300000,'uncached_input_tokens':60000,'output_tokens':4000}
manifest={'code_sha':sha,'model':'gpt-6-luna','reasoning_effort':'medium','cli_version':subprocess.check_output(['codex','--version'],text=True).strip(),'case':'deliver','domain_id':'domain:missing','guards':limits,'source_database_sha256':hashes,'restored_source_hash_verified':restored,'raw_sources_unavailable':missing,'approved_target':state['proposal']['payload']['results'][0]['target'],'reported_result':state['proposal']['payload']['results'][0]['reported'],'prior_retained_domains':sorted(keep),'initial_revision':state['revision'],'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),'selection_hypothesis':'Operator-only: distinguish discontinuation, incomplete composite follow-up and survival status; do not infer complete primary outcome data from ITT inclusion. Selected using original trial evidence, not reference judgments. No page/count/answer hint supplied to model.','qualification':'Fresh relative to today engineering probes; existing Oct1 Code approved Result retained, D1/D2 retained solely for workflow sequence; D3/later active records and derivative delivery removed in new copy. Historical canonical rows retained; no status/history tool exposed. Not a cold full-trial assessment. Human label scope unknown; no validated accuracy claim or relabeling. Reference metadata kept outside model workspace.','no_invocation_retry':True,'manual_repairs_during_run':False}
(root/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');(root/'seed-state.json').write_text(json.dumps(state,indent=2)+'\n')
print('Prepared frozen DELIVER D3, restored',len(restored),'raw sources unavailable',len(missing),'exact model',manifest['model'],'effort',manifest['reasoning_effort'])
