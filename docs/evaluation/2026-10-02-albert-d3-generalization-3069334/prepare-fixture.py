from pathlib import Path
import sys, json
repo=Path('/home/ali/Documents/Codex/2026-10-02/task-4/rob2-kit')
controls=repo.parent/'diagnostics/probe-controls-albert-3069334'
controls.mkdir(exist_ok=True)
for name in ('domain_probe_controls.py','run_domain_probe.py','domain_probe_limits.json'):
 (controls/name).write_bytes((repo/'scripts'/name).read_bytes())
limits=json.loads((controls/'domain_probe_limits.json').read_text())
limits.update(input_tokens=800000,tool_calls=20)
(controls/'domain_probe_limits.json').write_text(json.dumps(limits,indent=2)+'\n')
p=controls/'run_domain_probe.py'
p.write_text(p.read_text().replace('_REPO = Path(__file__).resolve().parents[1]','_REPO = Path('+repr(str(repo))+')'))
sys.path.insert(0,str(controls))
from domain_probe_controls import write_controls, approved_limits
old=(repo/'docs/evaluation/2026-10-02-hosted-deliver-d3-db8e68d/prepare-fixture.py').read_text()
old=old.replace("assert sha=='db8e68d2df7cb3b3720b2ce8ee3c9ab75d848052'","assert sha=='9497c9f6c2323dd2bbff550663c453856bf441f2'").replace('frozen-deliver-d3-db8e68d','frozen-albert-d3-3069334')
old=old.replace('9497c9f6c2323dd2bbff550663c453856bf441f2','3069334ac25f831086ea5562c746c19215b6494f').replace('deliver','albert-2013').replace('visual_albert-2013ies','visual_deliveries')
a=old.index("prompt='''");b=old.index('manifest=',a)
prompt='Assess only Domain 3 for albert-2013 using its existing approved Result and current production guidance. Start with get_domain_context for domain:missing and complete all returned context pages. Read the required captured main report and relevant captured source evidence, preserving the exact approved groups, outcome, assignment effect, analysis and timing. The local main article is restored with matching hashes. A historical registry projection lacks its retained raw bytes; retain that limitation and do not capture a replacement or access the network. Submit the complete active answer path through save_domain_judgment and use its server-computed judgment. Retain material unknowns and substantive counterpoints. Stop after D3; do not assess other Domains, finalize, use outside knowledge or perform coding. Return a concise account of scientific warrants, accepted checkpoint or failure (400 words or less).'
old=old[:a]+'prompt='+repr(prompt)+'\nlimits=approved_limits().model_dump()\n'+old[b:]
old=old.replace("(root/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\\n');", "manifest['hosted_declaration_check_before_science']=False\nmanifest['scientific_implementation_sha']='9497c9f6c2323dd2bbff550663c453856bf441f2'\nmanifest['selection_hypothesis']='Operator-only: source-rich continuous disability endpoint with appreciable incomplete follow-up, selected from retained article evidence and availability, not human labels. No counts/pages/answers supplied to model.'\nmanifest['guard_change_authorization']='Parent explicitly approved 800k total input and 20 tools; other limits retained. No production code change.'\nwrite_controls(root,manifest,prompt)\n")
# Resume the partially prepared new copy; no model invocation or controls existed.
import sqlite3, hashlib, subprocess, shutil
from rob2_kit.application.domains import get_domain_context
from rob2_kit.application._state import _state
root=repo.parent/'diagnostics/frozen-albert-d3-3069334'
w=root/'workspace';internal=w/'.rob2-kit';state=_state(w)
sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()
source=Path('/home/ali/Documents/Code/rob2-kit-benchmark/benchmark-luna6-medium-2026-10-01/cases/albert-2013/.rob2-kit')
hashes={name:hashlib.sha256((source/name).read_bytes()).hexdigest() for name in ('canonical.sqlite3','derivative.sqlite3')}
keep={'domain:randomization','domain:deviations'}
with sqlite3.connect(internal/'derivative.sqlite3') as c:
 for table in ['renders','visual_deliveries','evidence_handles','search_receipts','search_sessions','search_candidates','search_domain_associations','search_evidence_provenance','search_evidence_provenance_history','page_reads','domain_context_delivery','domain_context_views']:c.execute('DELETE FROM '+table)
exec(compile(old[old.index('restored=[];'):],__file__,'exec'))
