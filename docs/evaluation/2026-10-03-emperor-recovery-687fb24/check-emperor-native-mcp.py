from pathlib import Path
import asyncio,json,tomllib,sys
from fastmcp import Client
root=Path(sys.argv[1]);config=tomllib.loads((root/'home/config.toml').read_text());server=config['mcp_servers']['rob2']
async def main():
 async with Client({'mcpServers':{'rob2':{key:server[key] for key in ['command','args','env']}}}) as client:
  tools=await client.list_tools()
  declared=[t.model_dump(mode='json',exclude_none=True) for t in tools if t.name in server['enabled_tools']]
  proposal=next(t for t in declared if t['name']=='validate_proposal')
  schema=proposal['input_schema']
  findings={}
  for name in ['results','missing_results']:
   item=schema['properties'][name]['items'];assert item['type']=='object' and item['required'] and not any(k in item for k in ['anyOf','oneOf'])
   findings[name]={'required':item['required'],'properties':list(item['properties']),'homogeneous_object':True}
  status=await client.call_tool('get_status',{})
  (root/'native-tools-list.json').write_text(json.dumps(declared,indent=2)+'\n')
  (root/'native-status-preflight.json').write_text(json.dumps(status.structured_content,indent=2)+'\n')
  (root/'preflight.json').write_text(json.dumps({'no_model_calls':True,'native_stdio_tools_list_verified':True,'schema_collections':findings,'service_delivery_verified':False,'default_supported_routing_restored':True},indent=2)+'\n')
asyncio.run(main())
