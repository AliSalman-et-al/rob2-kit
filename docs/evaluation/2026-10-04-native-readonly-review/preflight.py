"""No-inference native transport checks on finalized, write-protected scientific state."""
from pathlib import Path
import asyncio,hashlib,json,os,sqlite3,zipfile
from fastmcp import Client
from fastmcp.client.transports import StdioTransport
R=Path(__file__).resolve().parent;S=json.loads((R/'setup.json').read_text());D=Path(S['staging']);W=Path(S['workspace'])
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(n,x):(R/n).write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
def protected():
 for name,h in json.loads((R/'protected-staging.json').read_text()).items():assert sha(Path(name))==h
 for name,h in json.loads((R/'original-preservation.json').read_text()).items():assert sha(Path(name))==h

def envelope(result):
 if isinstance(result.structured_content,dict):return result.structured_content
 return next(json.loads(c.text) for c in result.content if c.type=='text' and c.text.startswith('{'))
async def main():
 protected();transport=StdioTransport(command=S['python'],args=['-m','rob2_kit.interfaces.cli.app','mcp-codex'],env={**os.environ,'ROB2_WORKSPACE':str(W),'PYTHONPATH':str(Path(S['code'])/'src'),'PYTHONDONTWRITEBYTECODE':'1'})
 rows=[]
 async with Client(transport) as client:
  tools={t.name:t for t in await client.list_tools()};write('tool-inventory.json',[t.model_dump(mode='json',exclude_none=True) for t in tools.values() if t.name in S['allowed_tools']])
  assert set(S['allowed_tools'])<=set(tools)
  for name in ['get_status','list_sources','read_pages','search_sources','search_sources_batch','render_page']:
   assert tools[name].annotations is not None and tools[name].annotations.readOnlyHint
  assert tools['render_page'].output_schema is None and tools['render_page'].meta['rob2_receipt_schema']
  async def call(name,args):
   result=await client.call_tool(name,args);e=envelope(result);write('preflight-'+name+'.json',e);assert e['outcome']=='success',(name,e)
   rows.append({'tool':name,'arguments':args,'head':e['head'],'outcome':e['outcome']});protected();return e,result
  status,_=await call('get_status',{});assert status['head']['phase']=='finalized' and status['head']['state_revision']==12
  review,_=await call('review_trial',{'trial_id':'gupta-2024','expected_revision':12,'domain_id':'domain:measurement'})
  assert review['head']['phase']=='finalized' and review['head']['state_revision']==12 and review['data']['retry']
  assert review['data']['review_page']['mode']=='summary' and not review['data']['review_page']['complete']
  bundle=next((W/'.rob2-kit/finalized').glob('*.zip'))
  with zipfile.ZipFile(bundle) as z:c=json.loads(z.read('canonical.json'))
  saved=c['domain_records']['gupta-2024:domain:measurement'];shown=review['data']['domain_findings'][0]
  assert saved['identity']==shown['checkpoint_identity'];assert len(saved['answers'])==len(shown['answers'])==3
  for a,b in zip(saved['answers'],shown['answers'],strict=True):
   assert a['question_id']==b['question_id'] and a['answer']==b['answer'] and a['justification']==b['justification'] and a['unknowns']==b['unknowns'] and a['counterevidence']==b['counterevidence']
   assert [x['evidence'] for x in a['bases'] if x.get('evidence')]==[x['evidence']['identity'] for x in b['bases'] if x.get('evidence')]
  sources,_=await call('list_sources',{'trial_id':'gupta-2024'})
  action=shown['answers'][0]['evidence_expansions'][0];window=action['windows'][0]
  await call('read_pages',{'trial_id':'gupta-2024','windows':[window]})
  render,result=await call('render_page',{'trial_id':'gupta-2024','source_id':window['source_id'],'page':window['page']})
  images=[x for x in result.content if x.type=='image'];assert len(images)==1
  import base64
  png=base64.b64decode(images[0].data);write('preflight-render-identity.json',{'png_sha256':hashlib.sha256(png).hexdigest(),'bytes':len(png),'receipt':render})
  # Generic outcome query, independent of known citation defect; never supplied as model input.
  await call('search_sources',{'trial_id':'gupta-2024','query':'bronchopulmonary','mode':'all','limit':3})
 write('preflight.json',{'success':True,'model_calls':0,'native_entrypoint':'mcp-codex','operator_calls':rows,'closed_review_readonly_retry':True,'scientific_protected_files_unchanged':True,'source_hashes_from_bundle':[{'id':s['id'],'sha256':s['sha256']} for t in c['batch']['trials'] for s in t['sources']],'all_D4_claims_and_citations_match_finalized_bundle':True,'review_readonly_annotation_note':'review_trial is generally mutation-annotated; the finalized closed-review branch is an existing retry that does not commit. Scientific stores/source files are OS write-protected; only derivative navigation cache changes.'})
 print('Native finalized review/source preflight passed; no model calls.')
asyncio.run(main())
