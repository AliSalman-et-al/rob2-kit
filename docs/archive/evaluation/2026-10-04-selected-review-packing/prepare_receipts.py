"""Preserve exact Baby cached snapshot and reconstruct unrelated EXSCEL projection."""
from pathlib import Path
import hashlib,json,sqlite3,shutil,subprocess
from rob2_kit.application.trials import _review_domain_findings
from rob2_kit.application.source_handles import public_source_references
R=Path(__file__).resolve().parent;ROOT=R.parents[2];D=ROOT.parent/'diagnostics/selected-review-packing-20261004'
assert not D.exists(),'Preserve diagnostic preparation; do not overwrite'
D.mkdir()
M=json.loads((ROOT/'docs/evaluation/2026-10-04-gupta-fork-continuation/run-manifest.json').read_text());workspace=Path(M['staging'])/'workspace'
page=json.loads((ROOT/'docs/evaluation/2026-10-04-source-audit-design/native-measurement-review.json').read_text())['data']['review_page'];view_id=page['next_cursor'].split('.')[1]
p=workspace/'.rob2-kit/derivative.sqlite3';before=hashlib.sha256(p.read_bytes()).hexdigest()
with sqlite3.connect(p.as_uri()+'?mode=ro',uri=True) as con:row=con.execute('SELECT snapshot FROM review_views WHERE view_id=?',(view_id,)).fetchone()
assert row;baby=json.loads(row[0]);assert hashlib.sha256(p.read_bytes()).hexdigest()==before
(R/'baby-snapshot.json').write_text(json.dumps(baby,ensure_ascii=False,indent=2)+'\n')
old=ROOT.parent/'diagnostics/frozen-exscel-bd92ec8/workspace';original={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in old.rglob('*') if p.is_file()}
copy=D/'exscel-workspace';shutil.copytree(old,copy)
archive=ROOT/'docs/evaluation/2026-10-03-exscel-host-recovery';rows=[json.loads(l) for l in (archive/'turn-0.events.jsonl').read_text().splitlines()];snap=next(r['item']['result']['structured_content'] for r in rows if r.get('type')=='item.completed' and r.get('item',{}).get('id')=='item_35')
state=json.loads((archive/'frozen-final-state.json').read_text());snap['data']['domain_findings']=_review_domain_findings(copy,state,'exscel');snap=public_source_references(snap)
# The retained envelope was already a summary. Use the complete re-projected findings,
# not its old summary flag; identities and saved scientific content stay unchanged.
snap['data'].pop('review_page',None)
(R/'exscel-snapshot.json').write_text(json.dumps(snap,ensure_ascii=False,indent=2)+'\n')
assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in original.items())
(R/'source-preservation.json').write_text(json.dumps({'baby_derivative_sha256':before,'baby_source_path':str(p),'exscel_original_files':original,'exscel_original_unchanged':True,'projection_only':True,'code_base':'5b968820d17f5f7a0432df364353792c46a0f016'},indent=2)+'\n')
# Exact old implementation for before comparison; no model or assessment writes.
code=D/'before-code';code.mkdir();tar=D/'before.tar';tar.write_bytes(subprocess.check_output(['git','archive','5b96882','src']));subprocess.run(['tar','xf',str(tar),'-C',str(code)],check=True)
print('Exact Baby snapshot and unrelated EXSCEL saved projection prepared; originals unchanged.')
