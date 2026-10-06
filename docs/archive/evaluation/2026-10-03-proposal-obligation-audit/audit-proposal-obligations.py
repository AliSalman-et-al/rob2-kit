from pathlib import Path
import asyncio, hashlib, importlib.util, json, tempfile
from fastmcp import Client
from fastmcp.exceptions import ToolError
from rob2_kit.interfaces.mcp.server import mcp
repo=Path.cwd();out=repo/'docs/evaluation/2026-10-03-proposal-obligation-audit';out.mkdir(exist_ok=True)
spec=importlib.util.spec_from_file_location('controls',repo/'tests/test_typed_proposal_routes.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
async def declarations():
 async with Client(mcp) as client:
  return [t.model_dump(mode='json',exclude_none=True) for t in await client.list_tools()]
tools=asyncio.run(declarations());(out/'current-native-tools.json').write_text(json.dumps(tools,indent=2)+'\n')
comparisons=[]
prior=repo/'docs/evaluation/2026-10-03-emperor-recovery-687fb24'
before=json.loads((repo/'docs/evaluation/2026-10-03-proposal-field-feedback/unchanged-request-comparison.json').read_text())
for ordinal,attempt in enumerate(json.loads((prior/'proposal-attempts.json').read_text()),1):
 with tempfile.TemporaryDirectory() as workspace:
  try:m._native(Path(workspace),attempt['arguments']);raise AssertionError('must remain invalid')
  except ToolError as exc:after=json.loads(str(exc))
 old=before[ordinal-1]['after'];old_count=sum(x['count'] for x in old['defects'])+old['additional_defects'];new_count=sum(x['count'] for x in after['defects'])+after['additional_defects']
 assert old_count-new_count==(2 if ordinal==1 else 0)
 comparisons.append({'attempt':ordinal,'request_sha256':hashlib.sha256(json.dumps(attempt['arguments'],sort_keys=True).encode()).hexdigest(),'request_modified':False,'before_raw_defects':old_count,'after_raw_defects':new_count,'after':after,'saved':False,'no_model_calls':True})
(out/'unchanged-request-replay.json').write_text(json.dumps(comparisons,indent=2)+'\n')
summary={}
for t in tools:
 if t['name'] in ['validate_proposal','save_proposal','save_domain_judgment']:
  schema=t['input_schema'];summary[t['name']]={'declaration_bytes':len(json.dumps(t,separators=(',',':')).encode()),'required_arguments':schema.get('required',[])}
summary['source_of_truth']=['src/rob2_kit/skills/rob2-assess/SKILL.md','src/rob2_kit/skills/rob2-assess/references/result.md','live native tools/list','current application validators'];summary['no_model_calls']=True
(out/'contract-summary.json').write_text(json.dumps(summary,indent=2)+'\n');(out/'audit-proposal-obligations.py').write_text(Path(__file__).read_text());print(json.dumps(comparisons,indent=2))
