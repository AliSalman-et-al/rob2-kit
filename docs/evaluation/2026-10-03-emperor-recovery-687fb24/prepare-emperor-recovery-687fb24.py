from pathlib import Path
import shutil,json,hashlib,subprocess
base=Path(__file__).resolve().parent
failed=base/'frozen-emperor-primary-proposal-687fb24'
prior=base/'frozen-emperor-primary-proposal-bef6a06'
root=base/'frozen-emperor-recovery-687fb24';assert not root.exists();root.mkdir()
shutil.copytree(failed/'workspace',root/'workspace')
(root/'home').mkdir()
for name in ['auth.json','models_cache.json']:shutil.copyfile(prior/'home'/name,root/'home'/name)
config=(prior/'home/config.toml').read_text().replace(str(prior),str(root)).replace('frozen-proposal-bef6a06-code','frozen-proposal-687fb24-code').replace(', "save_proposal"','')
assert 'chatgpt_base_url' not in config and 'responses_websockets' not in config
(root/'home/config.toml').write_text(config)
for name in ['instructions.md','prompt.txt','seed-state.json']:shutil.copyfile(failed/name,root/name)
manifest=json.loads((failed/'manifest.json').read_text());manifest.pop('hosted_schema_capture');manifest['recovery_of_preinference_failure']=str(failed);manifest['guard_authorization']='Explicit recovery authorization after single zero-token capture/routing failure: one fresh invocation using prior working supported direct-MCP route, frozen687fb24; no further automatic invocation.';manifest['routing_configuration']='Original supported CLI default backend routing restored; no proxy/base URL/WebSocket/compression overrides. Existing isolated authenticated setup reused without auth/security edits.'
(root/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(root)
