from pathlib import Path
import asyncio,json,hashlib,importlib.util,tempfile,shutil
from fastmcp import Client
from fastmcp.exceptions import ToolError
from rob2_kit.interfaces.mcp.server import mcp
repo=Path.cwd();out=repo/'docs/evaluation/2026-10-03-proposal-selection-redesign';out.mkdir(exist_ok=True)
old=json.loads((repo/'docs/evaluation/2026-10-03-proposal-obligation-audit/unchanged-request-replay.json').read_text());inventory=[]
for row in old:
 for d in row['after']['defects']:
  path=d['path'];n=d['count'];category='field nesting/naming';reason='Content is supplied in the wrong typed shape; no safe automatic coercion is introduced.'
  if path.endswith('/clarity'):
   category='scientific information genuinely missing';reason='Caller facet declarations are missing or malformed. Source absence is not established; explicit exactness cannot be derived from HR/CI or a prose scope assertion.'
  elif path.endswith('/evidence') or path.endswith('/evidence_basis'):
   category='redundant server-known data';reason='Selected passage handles already carry kind, identity and coordinates. Advanced numerical proofs remain necessary when they add scientific mapping; plain handles/prose are not such proofs.'
  elif path=='/results/1' or path=='/results/1/missing_facts':
   category='field nesting/naming';reason='Unresolved facts about the selected candidate were entered as a second Result for the same Trial. A complete second Result is not scientifically required.'
  inventory.append({'request':row['attempt'],'path':path,'raw_defect_count':n,'category':category,'interpretation':reason,'raw_feedback':d})
assert sum(x['raw_defect_count'] for x in inventory if x['request']==1)==7
assert sum(x['raw_defect_count'] for x in inventory if x['request']==2)==25
(out/'defect-inventory.json').write_text(json.dumps({'source':'../2026-10-03-proposal-obligation-audit/unchanged-request-replay.json','defects':inventory,'unsupported_specificity_note':'The requests assert exact while naming unresolved hospitalization criteria/window issues. This is a scientific calibration issue, not an additional counted construction defect; no desired relation is inferred.'},indent=2)+'\n')
spec=importlib.util.spec_from_file_location('controls',repo/'tests/test_typed_proposal_routes.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
replays=[]
for n,a in enumerate(json.loads((repo/'docs/evaluation/2026-10-03-emperor-recovery-687fb24/proposal-attempts.json').read_text()),1):
 with tempfile.TemporaryDirectory() as w:
  try:m._native(Path(w),a['arguments']);raise AssertionError('retired shape must be rejected')
  except ToolError as e:reply=json.loads(str(e))
 replays.append({'request':n,'request_sha256':hashlib.sha256(json.dumps(a['arguments'],sort_keys=True).encode()).hexdigest(),'unchanged':True,'outcome':'Retired public contract rejected; not a repaired or successfully proposed scientific Result.','reply':reply})
(out/'unchanged-request-replays.json').write_text(json.dumps(replays,indent=2)+'\n')
async def declarations():
 async with Client(mcp) as client:return [t.model_dump(mode='json',exclude_none=True) for t in await client.list_tools()]
tools=asyncio.run(declarations());tool=next(t for t in tools if t['name']=='validate_proposal');(out/'current-validate-proposal.json').write_text(json.dumps(tool,indent=2)+'\n')
beforetools=json.loads((repo/'docs/evaluation/2026-10-03-proposal-obligation-audit/current-native-tools.json').read_text());before=next(t for t in beforetools if t['name']=='validate_proposal')
summary={'before_public_contract':'0.10.0','after_public_contract':'0.11.0','before_required_arguments':before['input_schema']['required'],'after_required_arguments':tool['input_schema']['required'],'before_declaration_bytes':len(json.dumps(before,separators=(',',':')).encode()),'after_declaration_bytes':len(json.dumps(tool,separators=(',',':')).encode()),'source_only_model_calls':0,'scope_inference_added':False,'canonical_or_verifier_format_changed':False,'historical_public_aliases_added':False}
(out/'before-after-contract.json').write_text(json.dumps(summary,indent=2)+'\n')
for n in ['selection-scientific-tests.txt','selection-contract-final-tests.txt','selection-release-tests.txt','selection-preservation-tests.txt','selection-historical-verification.json']:
 if (repo.parent/'diagnostics'/n).exists():shutil.copyfile(repo.parent/'diagnostics'/n,out/n)
(out/'record-selection-redesign.py').write_text(Path(__file__).read_text());print(json.dumps(summary,indent=2))
