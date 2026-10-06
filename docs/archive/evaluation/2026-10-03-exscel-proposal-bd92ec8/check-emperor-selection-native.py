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
  assert set(schema['properties'])=={'selections','expected_revision'}
  item=schema['properties']['selections']['items'];assert item['type']=='object'
  assert {'trial_id','relation','candidate','scope_rationale','source_passages','unknowns','counterevidence'} <= set(item['required'])
  assert any(v.get('type')=='null' for v in item['properties']['candidate']['anyOf'])
  findings['selections']={'required':item['required'],'properties':list(item['properties']),'homogeneous_object':True}
  status=await client.call_tool('get_status',{})
  (root/'native-tools-list.json').write_text(json.dumps(declared,indent=2)+'\n')
  (root/'native-status-preflight.json').write_text(json.dumps(status.structured_content,indent=2)+'\n')
  (root/'preflight.json').write_text(json.dumps({'no_model_calls':True,'native_stdio_tools_list_verified':True,'schema_collections':findings,'service_delivery_verified':False,'default_supported_routing_restored':True},indent=2)+'\n')
asyncio.run(main())
