"""Freeze an unchanged finalized-source copy; enforce canonical/source read-only files."""
from pathlib import Path
import hashlib,json,shutil,sqlite3,subprocess,os,stat
R=Path(__file__).resolve().parent;ROOT=R.parents[2];D=ROOT.parent/'diagnostics/native-readonly-review-20261004'
assert not D.exists(),'Do not overwrite preflight'
assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()=='d4aa130f49d88c553bf10b9c3920960422266c89'
D.mkdir();prior=json.loads((ROOT/'docs/evaluation/2026-10-04-gupta-fork-continuation/run-manifest.json').read_text());original=Path(prior['staging'])/'workspace'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
original_hashes={str(p):sha(p) for p in original.rglob('*') if p.is_file()}
workspace=D/'workspace';shutil.copytree(original,workspace)
assert all(sha(workspace/Path(name).relative_to(original))==h for name,h in original_hashes.items())
code=D/'code';code.mkdir();tar=D/'code.tar';tar.write_bytes(subprocess.check_output(['git','archive','d4aa130','src','scripts','pyproject.toml']));subprocess.run(['tar','xf',str(tar),'-C',str(code)],check=True)
PY='/home/ali/Documents/Codex/2026-10-02/task/rob2-kit/.venv/bin/python';subprocess.run([PY,'-m','rob2_kit.interfaces.cli.app','export-skill','--output',str(D/'rob2-assess')],env={**os.environ,'PYTHONPATH':str(code/'src')},check=True,capture_output=True)
protected={}
for p in workspace.rglob('*'):
 if not p.is_file() or p.name=='derivative.sqlite3':continue
 p.chmod(0o444);protected[str(p)]=sha(p)
for p in workspace.rglob('*'):
 if p.is_dir() and p.name!='.rob2-kit':p.chmod(0o555)
workspace.chmod(0o555)
# SQLite itself must refuse scientific-ledger writes; verify with a rolled-back same-value attempt.
canonical=workspace/'.rob2-kit/canonical.sqlite3';connection=sqlite3.connect(canonical)
try:
 try:
  connection.execute('UPDATE records SET payload=payload')
 except sqlite3.OperationalError as error:
  assert 'readonly' in str(error).lower(),str(error)
  readonly_error=str(error)
 else:raise AssertionError('Canonical write protection not enforced')
finally:connection.rollback();connection.close()
assert all(sha(Path(p))==h for p,h in protected.items())
(R/'original-preservation.json').write_text(json.dumps(original_hashes,indent=2)+'\n');(R/'protected-staging.json').write_text(json.dumps(protected,indent=2)+'\n')
manifest={'base_sha':'d4aa130f49d88c553bf10b9c3920960422266c89','staging':str(D),'original_finalized_fork_workspace':str(original),'workspace':str(workspace),'python':PY,'skill':str(D/'rob2-assess/SKILL.md'),'skill_sha256':sha(D/'rob2-assess/SKILL.md'),'code':str(code),'model':'gpt-6-luna','effort':'medium','canonical_write_probe':readonly_error,'canonical_source_bundle_files_readonly':True,'derivative_navigation_cache_writable':True,'allowed_tools':['get_status','review_trial','list_sources','read_pages','search_sources','search_sources_batch','render_page'],'forbidden_operations_not_enabled':['prepare_batch','save_proposal','request_proposal_approval','save_domain_judgment','close_trial','finalize_batch','save_working_checkpoint','discard'],'limits':{'turns':1,'tools':12,'output_tokens':3000,'wall_seconds':360,'idle_seconds':120,'input_telemetry_only':True},'credentials_read_or_copied':False}
(R/'setup.json').write_text(json.dumps(manifest,indent=2)+'\n');print(json.dumps({'staging':str(D),'canonical_write_probe':readonly_error,'protected_files':len(protected),'source_copy_byte_identical':True}))
