"""Offline acceptance of the built wheel in a disposable environment."""
import asyncio,base64,hashlib,importlib.metadata,importlib.util,json,os,shutil,subprocess,sys
from pathlib import Path
from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from rob2_kit.application.intake import prepare_batch_for_outcome
from rob2_kit.interfaces.mcp.contracts import output_schema
import rob2_kit.interfaces.mcp.codex as installed
R=Path(__file__).resolve().parent
REPO=R.parent.parent/'rob2-kit';wheel=R/'dist/rob2_kit-0.11.0-py3-none-any.whl'
assert str(Path(installed.__file__).resolve()).startswith(str(R/'venv'))
spec=importlib.util.spec_from_file_location('release_verify',REPO/'docs/release/verify.py');verifier=importlib.util.module_from_spec(spec);spec.loader.exec_module(verifier);verifier._verify_wheel_archive(wheel)
w=R/'workspace-4';d=w/'input/case';d.mkdir(parents=True)
shutil.copyfile(REPO/'docs/evaluation/2026-10-03-native-visual-delivery-smoke/source.pdf',d/'source.pdf');(d/'info.txt').write_text('Local synthetic visual delivery release fixture.\n');(d/'sources.toml').write_text('[roles]\n"info.txt"="main_article"\n"source.pdf"="supplement"\n')
prepare_batch_for_outcome(w,'visual inspection',0,['case'])
exe=R/'venv/bin/rob2';env={k:v for k,v in os.environ.items() if k!='PYTHONPATH'};env['ROB2_WORKSPACE']=str(w)
subprocess.run([str(exe),'export-skill','--output',str(R/'export/rob2-assess')],cwd=R,env=env,check=True,capture_output=True)
checks={'installed_source_from_disposable_venv':True,'actual_wheel_archive_contract':True}
async def run():
 forms={};schemas={}
 for mode in ['mcp','mcp-codex']:
  async with Client(StdioTransport(command=str(exe),args=[mode],env=env,cwd=str(R))) as client:
   catalog={t.name:t for t in await client.list_tools()};schemas[mode]=catalog
   sources=await client.call_tool('list_sources',{'trial_id':'case'});source=next(s for s in sources.structured_content['data']['sources'] if s['label']=='source.pdf')
   render=await client.call_tool('render_page',{'trial_id':'case','source_id':source['id'],'page':1})
   text=await client.call_tool('read_pages',{'trial_id':'case','source_id':source['id'],'pages':[1]})
   status=await client.call_tool('get_status',{})
   metadata=await client.call_tool('render_page',{'trial_id':'case','source_id':source['id'],'page':1,'inline':False})
   error=await client.call_tool('render_page',{'source_id':source['id'],'page':1},raise_on_error=False)
   forms[mode]={'render':{'content':[c.model_dump(mode='json') for c in render.content],'structured_content':render.structured_content},'status':status.structured_content,'read_pages':text.structured_content,'list_sources':sources.structured_content,'metadata_only':{'content':[c.model_dump(mode='json') for c in metadata.content],'structured_content':metadata.structured_content},'error':{'content':[c.model_dump(mode='json') for c in error.content],'is_error':error.is_error,'structured_content':error.structured_content}}
  (R/(mode+'-wire.json')).write_text(json.dumps(forms[mode],indent=2)+'\n')
 normal=forms['mcp']['render'];compat=forms['mcp-codex']['render'];receipt=json.loads(compat['content'][0]['text']);image=next(x for x in compat['content'] if x['type']=='image');pixels=base64.b64decode(image['data'])
 checks.update({'metadata_only_render_unchanged':forms['mcp']['metadata_only']==forms['mcp-codex']['metadata_only'],'metadata_only_structured_receipt_retained':forms['mcp-codex']['metadata_only']['structured_content'] is not None,'input_error_unchanged':forms['mcp']['error']==forms['mcp-codex']['error'],'input_error_remains_error':forms['mcp-codex']['error']['is_error'],'standard_render_structured_receipt_retained':normal['structured_content']==receipt,'compat_render_has_no_structured_shortcut':compat['structured_content'] is None,'original_text_and_image_blocks_unchanged':normal['content']==compat['content'][:-1],'full_schema_text_preserved':json.loads(compat['content'][-1]['text'])['receipt_schema']==output_schema('render_page'),'full_schema_catalog_metadata_preserved':schemas['mcp-codex']['render_page'].meta['rob2_receipt_schema']==schemas['mcp']['render_page'].output_schema,'standard_output_schema_retained':schemas['mcp']['render_page'].output_schema==output_schema('render_page'),'compat_render_output_schema_omitted':schemas['mcp-codex']['render_page'].output_schema is None,'png_hash_matches_receipt':receipt['data']['render']['png_sha256']=='sha256:'+hashlib.sha256(pixels).hexdigest(),'text_only_status_unchanged':forms['mcp']['status']==forms['mcp-codex']['status'],'text_only_read_pages_unchanged':forms['mcp']['read_pages']==forms['mcp-codex']['read_pages'],'source_metadata_unchanged':forms['mcp']['list_sources']==forms['mcp-codex']['list_sources']})
 assert all(checks.values()),checks
asyncio.run(run())
package=Path(installed.__file__).parents[2];hosts={n:json.loads((package/'hosts'/n).read_text()) for n in ['codex.json','claude-code.json']};checks['packaged_codex_launch']=hosts['codex.json']['mcp_command']=='rob2 mcp-codex';checks['packaged_standard_launch']=hosts['claude-code.json']['mcp_command']=='rob2 mcp';checks['skill_export_exact']=all((R/'export/rob2-assess'/p.relative_to(package/'skills/rob2-assess')).read_bytes()==p.read_bytes() for p in (package/'skills/rob2-assess').rglob('*') if p.is_file());assert all(checks.values())
report={'code_sha':subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip(),'wheel':wheel.name,'wheel_sha256':hashlib.sha256(wheel.read_bytes()).hexdigest(),'wheel_bytes':wheel.stat().st_size,'version':importlib.metadata.version('rob2-kit'),'python':sys.version,'installed_module':str(installed.__file__),'registry':'https://pypi.org/simple','build_backend_declared':'hatchling==1.32.0','build_and_install_isolated':True,'checks':checks,'new_model_calls':0,'clinical_accuracy_established':False,'dependencies':{d.metadata['Name']:d.version for d in importlib.metadata.distributions()}}
(R/'verification.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
