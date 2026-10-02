from pathlib import Path
import sys, json
repo=Path('/home/ali/Documents/Codex/2026-10-02/task-4/rob2-kit')
controls=repo.parent/'diagnostics/probe-controls-9497c9f'
controls.mkdir()
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
old=old.replace("assert sha=='db8e68d2df7cb3b3720b2ce8ee3c9ab75d848052'","assert sha=='9497c9f6c2323dd2bbff550663c453856bf441f2'").replace('frozen-deliver-d3-db8e68d','frozen-deliver-d3-9497c9f')
a=old.index("prompt='''");b=old.index('manifest=',a)
prompt='Assess only Domain 3 for deliver using its existing approved Result and current production guidance. Start with get_domain_context for domain:missing and complete all returned context pages. Read the required captured main report and relevant captured source evidence, preserving the exact approved groups, primary composite, assignment effect, analysis and timing. Main article and local PDFs are restored with matching hashes. A historical registry projection lacks its retained raw bytes; retain that limitation and do not capture a replacement or access the network. Submit the complete active answer path through save_domain_judgment and use its server-computed judgment. Retain material unknowns and substantive counterpoints. Stop after D3; do not assess other Domains, finalize, use outside knowledge or perform coding. Return a concise account of scientific warrants, accepted checkpoint or failure (400 words or less).'
old=old[:a]+'prompt='+repr(prompt)+'\nlimits=approved_limits().model_dump()\n'+old[b:]
old=old.replace("(root/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\\n');", "manifest['hosted_declaration_check_before_science']=False\nmanifest['guard_change_authorization']='Parent explicitly approved 800k total input and 20 tools; other limits retained. No production code change.'\nwrite_controls(root,manifest,prompt)\n")
exec(compile(old,__file__,'exec'))
