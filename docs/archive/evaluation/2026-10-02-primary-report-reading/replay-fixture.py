import asyncio,json,os,shutil,sqlite3
from pathlib import Path
from fastmcp import Client
from rob2_kit.application._state import _state
from rob2_kit.application.domains import _flow_navigation
from rob2_kit.interfaces.mcp.server import mcp
base=Path('/home/ali/Documents/Codex/2026-10-02/task-4')
root=base/'diagnostics/offline-primary-report-reading-final';root.mkdir()
workspace=root/'workspace';shutil.copytree(base/'diagnostics/frozen-deliver-d3-c341156/workspace',workspace)
with sqlite3.connect(workspace/'.rob2-kit/derivative.sqlite3') as c:
 for table in ['page_reads','domain_context_views','domain_context_delivery']:c.execute('DELETE FROM '+table)
os.environ['ROB2_WORKSPACE']=str(workspace)
sources=_state(workspace)['batch']['trials'][0]['sources']
nav=_flow_navigation(workspace,'deliver',sources)
(root/'structural-navigation.json').write_text(json.dumps(nav,indent=2)+'\n')
async def run():
 async with Client(mcp) as client:
  async def call(tool,args):
   v=await client.call_tool(tool,args);s=v.structured_content;assert s['outcome']=='success',s;return s
  before=await call('get_status',{})
  pages=[];args={'domain_id':'domain:missing'}
  while True:
   p=await call('get_domain_context',args);pages.append(p)
   cursor=p['data'].get('context_page',{}).get('next_cursor')
   if cursor is None:break
   args={'cursor':cursor}
  after=await call('get_status',{})
  appendix=next(x for x in sources if x['logical_path']=='nejmoa2206286_appendix.pdf')
  flow=next(w for w in nav[appendix['id']] if w['page']==27)
  coverage=next(x for x in pages[0]['data']['coverage'] if x['source_id']=='sh_'+appendix['id'].removeprefix('source_')[:16])
  window={**flow,'source_id':coverage['source_id']}
  read=await call('read_pages',{'trial_id':'deliver','windows':[window]})
  (root/'context-pages.json').write_text(json.dumps(pages,indent=2)+'\n')
  (root/'flow-page-delivered.json').write_text(json.dumps(read,indent=2)+'\n')
  status_before=before['data']['main_report_reading']['deliver'];status_after=after['data']['main_report_reading']['deliver']
  chunks=[x for p in pages for x in p['data'].get('primary_report',[])]
  assert status_after['status']=='complete',status_after
  assert {x['page'] for x in chunks}==set(range(1,11))
  summary={'model_inference':False,'canonical_assessment_modified':False,'source_database':'/home/ali/Documents/Code/rob2-kit-benchmark/benchmark-luna6-medium-2026-10-01/cases/deliver/.rob2-kit','offline_copy_of':'frozen-deliver-d3-c341156/workspace','context_page_count':len(pages),'context_pages':[{k:p['data'].get('context_page',{}).get(k) for k in ['index','section','count']} for p in pages],'main_before':status_before,'main_after':status_after,'primary_report_chunks':len(chunks),'primary_report_physical_pages':sorted({x['page'] for x in chunks}),'flow_navigation_window':window,'flow_read_delivered':True,'scientific_comprehension_or_new_judgment':False}
  (root/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps({k:summary[k] for k in ['context_page_count','primary_report_physical_pages','flow_navigation_window','flow_read_delivered']},indent=2))
asyncio.run(run())
