from pathlib import Path
import asyncio,hashlib,json,shutil
from fastmcp import Client
from fastmcp.client.transports import StdioTransport
R=Path(__file__).resolve().parent;P=R.parent/'freeman-native-d3';py=json.loads((R/'setup.json').read_text())['python']
def write(n,x):(R/n).write_text(json.dumps(x,indent=2)+'\n')
async def collect(name,profile):
 w=R/name;assert not w.exists();shutil.copytree(R/'workspace',w)
 tr=StdioTransport(command=py,args=['-m','rob2_kit.interfaces.cli.app','mcp-codex'],env={'ROB2_WORKSPACE':str(w),'PYTHONPATH':str(R/'code/src'),'PYTHONDONTWRITEBYTECODE':'1'},cwd=str(w))
 async with Client(tr) as client:
  status=(await client.call_tool('get_status',{})).structured_content;first=None;merged=None;args={'trial_id':'freeman-2020','domain_id':'domain:missing','guidance_profile':profile,'max_response_bytes':65536};receipts=[]
  for _ in range(20):
   e=(await client.call_tool('get_domain_context',args)).structured_content;receipts.append(e);assert e['outcome']=='success',e
   d=e['data']
   if merged is None:first=e;merged=dict(d)
   else:
    for k,v in d.items():
     if isinstance(v,list):merged.setdefault(k,[]).extend(v)
   cp=d.get('context_page',{});cursor=cp.get('next_cursor')
   if not cursor:break
   args={**args,'cursor':cursor}
  else:raise AssertionError('Preflight pagination unexpectedly stuck')
 write(name+'-native.json',{'status':status,'first':first,'merged':merged,'receipts':receipts});return merged

def nonguidance(d):
 out={k:v for k,v in d.items() if k not in {'guidance','traps','response_framework','official_guidance','guidance_profile','context_page'}}
 # The mode deliberately replaces scientific/maintainer explanatory scaffolding,
 # never question identity/wording/options/activation or source/Result facts.
 out['questions']=[{k:q[k] for k in ['id','wording','options','activation_status','activation','query_suggestions']} for q in out['questions']]
 out['comparison_cards']=[{k:v for k,v in card.items() if k not in {'propositions','paired_examples','prompt'}} for card in out['comparison_cards']]
 return out
async def main():
 a=await collect('parity-current','current');b=await collect('parity-prototype','official_d3_prototype');old=json.loads((P/'native-receipts.json').read_text())[1]['receipt']['data']
 na,nb,no=nonguidance(a),nonguidance(b),nonguidance(old)
 changed=[k for k in sorted(set(na)|set(nb)) if na.get(k)!=nb.get(k)];restored=[k for k in sorted(set(nb)|set(no)) if nb.get(k)!=no.get(k)]
 write('context-parity.json',{'same_starting_state_current_vs_prototype_non_guidance_equal':not changed,'reconstructed_prototype_vs_original_initial_non_guidance_equal':not restored,'mode_differences':changed,'restoration_differences':restored,'compared_fields':sorted(na),'ignored_only_guidance_or_pagination':['guidance','traps','response_framework','official_guidance','guidance_profile','context_page','question explanatory guidance fields','card propositions/paired_examples/prompt'],'native_tool_transport':'mcp-codex','scratch_only':'Context deliveries done only in separate parity clones; model starting workspace unconsumed','question_current_fields':list(a['questions'][0]),'question_prototype_fields':list(b['questions'][0])})
 if changed or restored:
  for k in set(changed+restored):write('parity-difference-'+k+'.json',{'current':na.get(k),'reconstructed_prototype':nb.get(k),'original_initial':no.get(k)})
 assert not changed and not restored,(changed,restored)
 print('Native source/Result/question/coverage parity passed against original prototype starting exposure.')
asyncio.run(main())
