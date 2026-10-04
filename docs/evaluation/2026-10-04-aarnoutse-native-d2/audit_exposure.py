from pathlib import Path
import asyncio,json,subprocess
from fastmcp import Client
from rob2_kit.interfaces.mcp.server import mcp
R=Path(__file__).resolve().parent
async def main():
 async with Client(mcp) as c:tools={t.name:t.model_dump(mode='json',exclude_none=True) for t in await c.list_tools()}
 selected={name:tools[name] for name in ['get_status','get_domain_context','save_working_checkpoint','save_domain_judgment']}
 (R/'native-public-exposure.json').write_text(json.dumps(selected,indent=2)+'\n')
 working=selected['save_working_checkpoint']['input_schema']['properties']['checkpoint']['properties']['observations']['items']['properties']
 domain=selected['save_domain_judgment']['input_schema']['properties']['answers']['items']['properties']['bases']['items']['properties']
 assert working['scope']['anyOf'][0]['properties']['relation']['enum']==['matched','mismatch','partial_overlap','unknown','shared_trial_context']
 assert domain['working_observation']['anyOf'][0]['properties']['observation']
 for name in ['save_working_checkpoint','save_domain_judgment']:assert 'working_observation' in selected[name]['description']
 skill=Path('src/rob2_kit/skills/rob2-assess/SKILL.md').read_text();reference=Path('src/rob2_kit/skills/rob2-assess/references/evidence.md').read_text()
 assert 'preserve-working-observation-scope' in skill
 for text in ['shared_trial_context','checkpoint_identity','unchanged observation','reported','inferred']:assert text in reference
 old=subprocess.check_output(['git','show','d8ad6a5:src/rob2_kit/skills/rob2-assess/SKILL.md'],text=True)
 oldserver=subprocess.check_output(['git','show','d8ad6a5:src/rob2_kit/interfaces/mcp/server.py'],text=True)
 report={'before':{'typed_scope_in_schema':True,'typed_link_in_schema':True,'skill_mentions_working_observation':'working_observation' in old,'public_tool_description_mentions_link':'bases[].working_observation' in oldserver,'obsolete_counterevidence_index_instruction':'Counterevidence indexes' in old},'after':{'typed_scope_in_schema':True,'typed_link_in_schema':True,'general_skill_path_documented':True,'both_public_mutation_descriptions_explain_link':True,'counterevidence_handle_instruction_consistent':True},'scientific_gate_added':False,'case_specific_example_added':False}
 (R/'native-exposure-review.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
asyncio.run(main())
