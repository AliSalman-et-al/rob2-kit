from pathlib import Path
import importlib.util,json,tempfile,shutil,hashlib
from fastmcp.exceptions import ToolError
repo=Path.cwd();prior=repo/'docs/evaluation/2026-10-03-emperor-recovery-687fb24';out=repo/'docs/evaluation/2026-10-03-proposal-field-feedback';out.mkdir(exist_ok=True)
spec=importlib.util.spec_from_file_location('controls',repo/'tests/test_typed_proposal_routes.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
comparisons=[]
for ordinal,attempt in enumerate(json.loads((prior/'proposal-attempts.json').read_text()),1):
 before=attempt['result']['content'][0]['text']
 with tempfile.TemporaryDirectory() as workspace:
  try:m._native(Path(workspace),attempt['arguments'])
  except ToolError as exc:after=str(exc)
 old=json.loads(before);new=json.loads(after)
 assert new['additional_defects']==0 and len(after.encode())<=4096
 comparisons.append({'attempt':ordinal,'request_sha256':hashlib.sha256(json.dumps(attempt['arguments'],sort_keys=True).encode()).hexdigest(),'request_modified':False,'before':old,'after':new,'before_bytes':len(before.encode()),'after_bytes':len(after.encode()),'before_hidden_defects':old['additional_defects'],'after_hidden_defects':new['additional_defects'],'after_represented_raw_defects':sum(d['count'] for d in new['defects']),'outcome':'Schema rejection; no application validation, source binding or saving invoked.'})
(out/'unchanged-request-comparison.json').write_text(json.dumps(comparisons,indent=2)+'\n')
shutil.copyfile(prior/'reading-status.json',out/'separate-reading-requirement.json')
shutil.copyfile(repo.parent/'diagnostics/proposal-grouped-feedback-tests.txt',out/'focused-tests-initial.txt')
shutil.copyfile(repo.parent/'diagnostics/proposal-grouped-identity-final.txt',out/'identity-control-final.txt')
shutil.copyfile(Path(__file__),out/'record-grouped-feedback-audit.py')
print(json.dumps([{k:v for k,v in c.items() if k not in ['before','after']} for c in comparisons],indent=2))
