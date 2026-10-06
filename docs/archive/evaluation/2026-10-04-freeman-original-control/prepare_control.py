from pathlib import Path
import json,hashlib,shutil,sqlite3
R=Path(__file__).resolve().parent;P=R.parent/'freeman-native-d3';w=R/'workspace'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def write(n,x):(R/n).write_text(json.dumps(x,indent=2)+'\n')
assert not w.exists(),'Preserve all earlier setup; no rebuild'
w.mkdir();shutil.copytree(P/'workspace/input',w/'input');d=w/'.rob2-kit';d.mkdir();shutil.copytree(P/'workspace/.rob2-kit/sources',d/'sources');shutil.copyfile(P/'initial-canonical.sqlite3',d/'canonical.sqlite3');shutil.copyfile(P/'workspace/.rob2-kit/derivative.sqlite3',d/'derivative.sqlite3');shutil.copyfile(P/'workspace/.rob2-kit/working.sqlite3',d/'working.sqlite3')
with sqlite3.connect(d/'canonical.sqlite3') as c:
 state=json.loads(c.execute("SELECT payload FROM records WHERE name='state'").fetchone()[0]);proposal=json.loads(c.execute("SELECT payload FROM records WHERE name='proposal'").fetchone()[0]);allowed=set(proposal['evidence']);assert not state.get('domain_records');assert state['revision']==3
with sqlite3.connect(d/'working.sqlite3') as c:assert c.execute('SELECT COUNT(*) FROM working_checkpoints').fetchone()[0]==0
cleared=['renders','visual_deliveries','search_receipts','search_sessions','search_candidates','search_domain_associations','search_evidence_provenance','search_evidence_provenance_history','domain_context_delivery','domain_context_views']
with sqlite3.connect(d/'derivative.sqlite3') as c:
 before={n:c.execute(f'SELECT COUNT(*) FROM {n}').fetchone()[0] for n in cleared}
 for n in cleared:c.execute(f'DELETE FROM {n}')
 for identity, in c.execute('SELECT identity FROM evidence_handles').fetchall():
  if identity not in allowed:c.execute('DELETE FROM evidence_handles WHERE identity=?',(identity,))
 c.execute("DELETE FROM page_reads WHERE phase!='proposal'");c.commit();c.execute('VACUUM')
 assert {x[0] for x in c.execute('SELECT identity FROM evidence_handles')}==allowed
 assert c.execute('SELECT DISTINCT phase FROM page_reads').fetchall()==[('proposal',)]
(R/'code').symlink_to(P/'code',target_is_directory=True);shutil.copytree(P/'rob2-assess',R/'rob2-assess')
s=json.loads((P/'setup.json').read_text());s.update(workspace=str(w),staging=str(R),code=str(R/'code'),skill=str(R/'rob2-assess/SKILL.md'),operator_reading='Identical canonical baseline; only original proposal derivative facts/preproposal reads restored; no assessment reading or model flow facts');write('setup.json',s)
for n in ['original-source-inventory.json','source-provenance.json','availability-manifest.json','availability-packet.bin','offline-availability-preflight.json']:
 shutil.copyfile(P/n,R/n)
shutil.copyfile(P/'initial-canonical.sqlite3',R/'initial-canonical.sqlite3')
prompt=(P/'prompt.txt').read_text();new=prompt.replace('guidance_profile="official_d3_prototype"','guidance_profile="current"');assert new!=prompt and new.replace('guidance_profile="current"','guidance_profile="official_d3_prototype"')==prompt;(R/'prompt.txt').write_text(new)
home=R/'home';home.mkdir();(home/'auth.json').symlink_to(P/'home/auth.json');cfg=(P/'home/config.toml').read_text().replace(str(P),str(R));(home/'config.toml').write_text(cfg)
shutil.copyfile(P/'run_once.py',R/'run_once.py');shutil.copyfile(P/'audit.py',R/'audit.py')
protected=json.loads((P/'protected-staging.json').read_text());protected.update({str(p):sha(p) for root in [w/'input',w/'.rob2-kit/sources'] for p in root.rglob('*') if p.is_file()});write('protected-staging.json',protected)
write('restoration.json',{'canonical_sha256':sha(d/'canonical.sqlite3'),'matches_original_baseline':sha(d/'canonical.sqlite3')==sha(P/'initial-canonical.sqlite3'),'proposal_evidence_identities':sorted(allowed),'derivative_removed_only_in_new_clone':before,'preproposal_read_count':12,'postapproval_reads':0,'working_records':0,'fresh_cli_home':True,'prototype_originals_untouched':True,'prompt_only_difference':'guidance profile value','implementation_and_skill':'same9c65667 frozen code and byte-identical skill','derivative_vacuumed':'Deleted prototype caches not left in clone free pages'})
print('Clean baseline clone reconstructed; no domain answers/model flow facts/search or visual history. No paid call.')
