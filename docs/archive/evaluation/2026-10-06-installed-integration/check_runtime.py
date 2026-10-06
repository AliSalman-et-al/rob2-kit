import asyncio,hashlib,importlib.metadata,json,os,subprocess,sys,zipfile
from pathlib import Path
from fastmcp import Client
from fastmcp.client.transports import StdioTransport
import rob2_kit
from rob2_kit.packs import SCIENTIFIC_PACK
from rob2_kit.application.finalization import verify_bundle,_scientific_contract_descriptor
R=Path(__file__).resolve().parent;repo=R.parent.parent
mode=sys.argv[1];w=R/('workspace-'+mode)
fixture=json.loads((repo/'tests/fixtures/official-guidance-audit-2019/elaborations.json').read_text())
q={x.id:x for x in SCIENTIFIC_PACK.questions}
for x in fixture['questions']:
 g=q[x['question_id']].guidance.official
 assert g.source_excerpt==x['normalized_excerpt'];assert g.source_sha256==fixture['source_sha256']
bundle=next((repo/'diagnostics/emperor-reduced-sol-low-preparation-20261005/workspace-run/.rob2-kit/finalized').glob('*.zip'))
assert verify_bundle(bundle)
with zipfile.ZipFile(bundle) as z:historical=json.loads(z.read('canonical.json'))['scientific_pack']
assert historical!=_scientific_contract_descriptor()
before=hashlib.sha256((w/'.rob2-kit/canonical.sqlite3').read_bytes()).hexdigest()
env={k:v for k,v in os.environ.items() if k!='PYTHONPATH'};env['ROB2_WORKSPACE']=str(w)
if mode=='installed':
 assert str(Path(rob2_kit.__file__).resolve()).startswith(str(R/'venv'))
 command=str(R/'venv/bin/rob2');args=['mcp']
else:
 env['PYTHONPATH']=str(repo/'src');command=sys.executable;args=['-c',"from rob2_kit.interfaces.mcp.server import mcp; mcp.run(transport='stdio')"]
async def run():
 async with Client(StdioTransport(command=command,args=args,env=env,cwd=str(R))) as c:
  ts=await c.list_tools();assert len(ts)==23
  catalog=[t.model_dump(mode='json') for t in ts]
  good=await c.call_tool('calculate_arithmetic',{'expression':'left - right','inputs':{'left':'-2.50','right':'1.25'},'units':'declared points','assumptions':['offline synthetic inputs']})
  assert good.structured_content['result']=='-3.75'
  rejected=[]
  for exp in ['1/0',"__import__('os').system('id')",'2 ** 3','1 +']:
   r=await c.call_tool('calculate_arithmetic',{'expression':exp},raise_on_error=False);assert r.is_error;rejected.append(exp)
  guides={}
  for doc in ['SKILL.md','references/randomization.md','references/missing.md','references/measurement.md']:
   r=await c.call_tool('read_guidance',{'document':doc},raise_on_error=False)
   assert not r.is_error
   guides[doc]=r.structured_content
  assert 'SKILL.md' in guides
  return catalog,good.structured_content,guides,rejected
catalog,arithmetic,guides,rejected=asyncio.run(run())
after=hashlib.sha256((w/'.rob2-kit/canonical.sqlite3').read_bytes()).hexdigest();assert before==after
report={'mode':mode,'module':rob2_kit.__file__,'python':sys.version,'dependencies':{n:importlib.metadata.version(n) for n in ['rob2-kit','fastmcp','httpx','mcp','pydantic','pymupdf','rapidfuzz']},'tool_count':len(catalog),'catalog':catalog,'questions':SCIENTIFIC_PACK.model_dump(mode='json'),'corrected_complete_official_blocks':len(fixture['questions']),'arithmetic':arithmetic,'malformed_rejected':rejected,'guidance':guides,'canonical_before':before,'canonical_after':after,'bundle':str(bundle),'bundle_sha256':hashlib.sha256(bundle.read_bytes()).hexdigest(),'historical_descriptor_differs_from_current':True,'product_bundle_verified':True}
(R/(mode+'-runtime.json')).write_text(json.dumps(report,indent=2)+'\n');print(mode,'runtime passed; tools',len(catalog))
