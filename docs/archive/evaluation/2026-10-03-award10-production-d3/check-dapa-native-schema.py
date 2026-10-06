from pathlib import Path
import asyncio,json,tomllib,sys
from fastmcp import Client
root=Path(sys.argv[1]);config=tomllib.loads((root/'home/config.toml').read_text());server=config['mcp_servers']['rob2']
async def main():
 async with Client({'mcpServers':{'rob2':{key:server[key] for key in ['command','args','env']}}}) as client:
  tools=[t.model_dump(mode='json',exclude_none=True) for t in await client.list_tools() if t.name in server['enabled_tools']]
  schema=next(t['input_schema'] for t in tools if t['name']=='save_domain_judgment')
  answer=schema['properties']['answers']['items'];assert answer['type']=='object' and answer['required']
  status=await client.call_tool('get_status',{})
  (root/'native-tools-list.json').write_text(json.dumps(tools,indent=2)+'\n');(root/'native-status-preflight.json').write_text(json.dumps(status.structured_content,indent=2)+'\n')
  (root/'launch-preflight.json').write_text(json.dumps({'no_model_calls':True,'save_answer_schema_fields':list(answer['properties']),'required':answer['required'],'no_request_proxy':True,'model':'gpt-6-luna','effort':'medium','provider_declaration_visibility':'Unobservable; native MCP declaration verified.'},indent=2)+'\n')
asyncio.run(main())
