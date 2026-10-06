from pathlib import Path
import sys
repo=Path('/home/ali/Documents/Codex/2026-10-02/task-4/rob2-kit')
sys.path.insert(0,str(repo/'scripts'))
from domain_probe_controls import write_controls
old=(repo/'docs/evaluation/2026-10-02-hosted-deliver-d3-db8e68d/prepare-fixture.py').read_text()
old=old.replace("assert sha=='db8e68d2df7cb3b3720b2ce8ee3c9ab75d848052'","assert sha=='c341156b9f1d43cee3510d688bc57bb074214e73'")
old=old.replace('frozen-deliver-d3-db8e68d','frozen-deliver-d3-c341156')
a=old.index("prompt='''");b=old.index("limits=",a)
prompt="Assess only Domain 3 for deliver using its existing approved Result and current production guidance. Start with get_domain_context for domain:missing and complete all returned context pages. Read the required captured main report and relevant captured source evidence, preserving the exact approved groups, primary composite, assignment effect, analysis and timing. Main article and local PDFs are restored with matching hashes. A historical registry projection lacks its retained raw bytes; retain that limitation and do not capture a replacement or access the network. Submit the complete active answer path through save_domain_judgment and use its server-computed judgment. Retain material unknowns and substantive counterpoints. Stop after D3; do not assess other Domains, finalize, use outside knowledge or perform coding. Return a concise account of scientific warrants, accepted checkpoint or failure (400 words or less)."
old=old[:a]+'prompt='+repr(prompt)+'\n'+old[b:]
old=old.replace("(root/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\\n');", "manifest['hosted_declaration_check_before_science']=False\nwrite_controls(root,manifest,prompt)\n")
exec(compile(old,__file__,'exec'))
