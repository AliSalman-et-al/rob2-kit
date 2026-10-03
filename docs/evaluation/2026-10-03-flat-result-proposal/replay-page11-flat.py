import asyncio,json,os,sqlite3,shutil
from pathlib import Path
from fastmcp import Client
from rob2_kit.interfaces.mcp.server import mcp
root=Path('/home/ali/Documents/Codex/2026-10-02/task-4')
source=root/'diagnostics/frozen-allsop-scope-b12fe45/workspace'
workspace=root/'diagnostics/page11-replay-flat'
workspace.mkdir()
internal=workspace/'.rob2-kit';internal.mkdir()
for name in ('canonical.sqlite3','derivative.sqlite3'):
 with sqlite3.connect(f'file:{source/".rob2-kit"/name}?mode=ro',uri=True) as a,sqlite3.connect(internal/name) as b:a.backup(b)
shutil.copytree(source/'.rob2-kit/sources',internal/'sources')
with sqlite3.connect(internal/'derivative.sqlite3') as c:c.execute('DELETE FROM page_reads')
events=[json.loads(line) for line in (root/'rob2-kit/docs/evaluation/2026-10-03-allsop-proposal-b12fe45/events.jsonl').read_text().splitlines()]
requests=[e['item']['arguments'] for e in events if e.get('item',{}).get('tool')=='read_pages' and e['item'].get('result')]
async def main():
 os.environ['ROB2_WORKSPACE']=str(workspace)
 async with Client(mcp) as client:
  for args in requests:
   response=await client.call_tool('read_pages',args)
   assert response.structured_content['outcome']=='success'
 with sqlite3.connect(internal/'derivative.sqlite3') as c:
  rows=c.execute('SELECT page,start_line,end_line FROM page_reads ORDER BY page,start_line').fetchall()
 assert (11,2,186) in rows
 assert not any(p==11 and start==1 for p,start,end in rows)
 output={'requests':requests,'durable_ranges_after':rows,'qualification':'Offline exact native read-request replay. Complete page11 lines2–186 durable; fragmented line1 remains unclaimed. No inference.'}
 out=root/'rob2-kit/docs/evaluation/2026-10-03-flat-result-proposal';out.mkdir(exist_ok=True)
 (out/'page11-replay.json').write_text(json.dumps(output,indent=2)+'\n')
 print(json.dumps(output))
asyncio.run(main())
