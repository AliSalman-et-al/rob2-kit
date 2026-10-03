import asyncio,json,sys
from fastmcp import Client
from rob2_kit.interfaces.mcp.server import mcp
async def main():
 async with Client(mcp) as client:
  rows=await client.list_tools()
  selected=[t.model_dump(mode='json',exclude_none=True) for t in rows if t.name in {'get_status','list_sources','read_pages','select_text_evidence','search_sources','search_sources_batch','render_page','select_visual_evidence','validate_proposal','save_proposal'}]
  print(json.dumps(selected,sort_keys=True))
asyncio.run(main())
