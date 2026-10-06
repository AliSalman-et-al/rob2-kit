"""Bounded offline actual-tool replay on disposable copies; no model or assessment mutation."""
from __future__ import annotations
import asyncio,hashlib,json,os,shutil,sqlite3
from pathlib import Path
from fastmcp import Client
from rob2_kit.application.evidence import _source_navigation_entries
from rob2_kit.interfaces.mcp.server import mcp
ROOT=Path(__file__).resolve().parents[3];R=Path(__file__).resolve().parent;D=ROOT.parent/'diagnostics/source-boundary-replay-20261004';D.mkdir(exist_ok=True)
CODE=Path('/home/ali/Documents/Code/rob2-kit-benchmark/benchmark-luna6-medium-2026-10-01/cases')
FROZEN=ROOT.parent/'diagnostics/frozen-exscel-bd92ec8/workspace'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def write(path:Path,x:object):path.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
def event(path:Path,item_id:str):
 for line in path.read_text().splitlines():
  row=json.loads(line);item=row.get('item',{})
  if row.get('type')=='item.completed' and item.get('id')==item_id:return {'trace':str(path),'trace_sha256':sha(path),'item':item_id,'tool':item.get('tool'),'arguments':item.get('arguments'), 'result':item['result']['structured_content']}
 raise ValueError(item_id)
history={
 'exscel-code-main-query':event(CODE/'exscel/turn-1.jsonl','item_9'),
 'exscel-recovery-flow-query':event(ROOT/'docs/evaluation/2026-10-03-exscel-host-recovery/turn-0.events.jsonl','item_17'),
 'exscel-recovery-plan-query':event(ROOT/'docs/evaluation/2026-10-03-exscel-host-recovery/turn-0.events.jsonl','item_31'),
 'exscel-recovery-plan-read':event(ROOT/'docs/evaluation/2026-10-03-exscel-host-recovery/turn-0.events.jsonl','item_32'),
 'dapa-correct-source-control':event(CODE/'dapa-hf/turn-2.jsonl','item_64')}
write(R/'historical-receipts.json',history)
originals={p:sha(p) for base in [FROZEN,CODE/'dapa-hf'] for p in (base/'.rob2-kit').glob('*.sqlite3')}
for p in originals:assert not Path(str(p)+'-wal').exists(),'Original DB must be checkpointed before read-only copying'
for trial,base in [('exscel',FROZEN),('dapa-hf',CODE/'dapa-hf')]:
 dest=D/trial
 if dest.exists():continue
 dest.mkdir();shutil.copytree(base/'.rob2-kit',dest/'.rob2-kit')
 if (base/'input').exists():shutil.copytree(base/'input',dest/'input')
summary={'scope':'No inference; actual public tools on disposable state/source copies','historical':{},'current':{},'adjacent_page_measurements':{},'navigation':{},'original_database_hashes':{str(p):h for p,h in originals.items()}}
for name,h in history.items():
 data=h['result']['data'];summary['historical'][name]={'tool':h['tool'],'arguments':h['arguments'],'response_bytes':len(json.dumps(h['result'],ensure_ascii=False,separators=(',',':')).encode()),'hit_windows':[{'page':x['page'],'start_line':x['start_line'],'end_line':x['end_line']} for x in data.get('hits',[])],'page_windows':[{k:x.get(k) for k in ['page','returned_start_line','returned_end_line','line_count','truncated','page_remainder','passage_ref']} for x in data.get('pages',[])],'remaining_windows':data.get('remaining_windows'),'truncated':data.get('truncated'),'matching_page_count':data.get('matching_page_count')}
async def run():
 for trial in ['exscel','dapa-hf']:
  workspace=D/trial;os.environ['ROB2_WORKSPACE']=str(workspace)
  async with Client(mcp) as client:
   async def call(label,tool,args):
    result=await client.call_tool(tool,args);s=result.structured_content;assert s['outcome']=='success',s;write(R/(label+'.json'),{'tool':tool,'arguments':args,'result':s});return s
   names=['exscel-code-main-query','exscel-recovery-flow-query','exscel-recovery-plan-query','exscel-recovery-plan-read'] if trial=='exscel' else ['dapa-correct-source-control']
   for name in names:
    hist=history[name];s=await call(name+'-current',hist['tool'],hist['arguments']);data=s['data'];summary['current'][name]={'response_bytes':len(json.dumps(s,ensure_ascii=False,separators=(',',':')).encode()),'hit_windows':[{'page':x['page'],'start_line':x['start_line'],'end_line':x['end_line']} for x in data.get('hits',[])],'page_windows':[{k:x.get(k) for k in ['page','returned_start_line','returned_end_line','line_count','truncated','page_remainder','passage_ref']} for x in data.get('pages',[])],'remaining_windows':data.get('remaining_windows'),'truncated':data.get('truncated'),'matching_page_count':data.get('matching_page_count')}
   if trial=='exscel':
    # Literal reference-following wording actually present in delivered main page8; not a historical query.
    ref=await call('figure-reference-following-current','search_sources',{'trial_id':trial,'source_id':'sh_08fbea6d1ed99fc0','query':'Figure S9','mode':'phrase'})
    summary['current']['figure-reference-following']={'historical_query':False,'query_provenance':'Delivered main physical8 points to Figure S9','hit_windows':[{'page':x['page'],'start_line':x['start_line'],'end_line':x['end_line']} for x in ref['data']['hits']],'response_bytes':len(json.dumps(ref,ensure_ascii=False,separators=(',',':')).encode())}
   source='sh_08fbea6d1ed99fc0' if trial=='exscel' else 'sh_62c074c3ab8e1f2f';page=45 if trial=='exscel' else 161
   one=await call(trial+'-single-page','read_pages',{'trial_id':trial,'source_id':source,'pages':[page]})
   two=await call(trial+'-adjacent-pages','read_pages',{'trial_id':trial,'source_id':source,'pages':[page,page+1]})
   def nbytes(s):return len(json.dumps(s,ensure_ascii=False,separators=(',',':')).encode())
   assert not two['data']['remaining_windows'] and nbytes(two)<=24000
   summary['adjacent_page_measurements'][trial]={'single_response_bytes':nbytes(one),'two_page_response_bytes':nbytes(two),'additional_bytes':nbytes(two)-nbytes(one),'initial_call_count_single':1,'initial_call_count_two_pages':1,'additional_calls_if_requested_together':0,'additional_calls_after_single_page_already_read':1,'same_page_text_preserved':one['data']['pages'][0]['numbered_text']==two['data']['pages'][0]['numbered_text'],'second_page_explicit_provenance':two['data']['pages'][1]['source_id']==source,'remaining_windows':two['data']['remaining_windows'],'second_page':page+1}
   # Navigation entries are literal source leads, not semantic continuation claims.
   with sqlite3.connect(workspace/'.rob2-kit/derivative.sqlite3') as c:
    full_id=c.execute('SELECT source_id FROM pages WHERE source_id LIKE ? LIMIT 1',(source.removeprefix('sh_')+'%',)).fetchone()
    if full_id is None:full_id=c.execute('SELECT source_id FROM pages WHERE source_id LIKE ? LIMIT 1',('source_'+source.removeprefix('sh_')+'%',)).fetchone()
    source_id=full_id[0];rows=c.execute('SELECT page,text FROM pages WHERE source_id=? ORDER BY page',(source_id,)).fetchall()
   entries=_source_navigation_entries(tuple(r[1] for r in rows),trial_id=trial,source_id=source_id)
   relevant=[x for x in entries if x['page'] in [page,page+1]];write(R/(trial+'-literal-navigation.json'),relevant);summary['navigation'][trial]=relevant
 for p,h in originals.items():assert sha(p)==h
 summary['original_databases_unchanged']=True;write(R/'summary.json',summary)
 print(json.dumps({'adjacent_page_measurements':summary['adjacent_page_measurements'],'original_databases_unchanged':True},indent=2))
asyncio.run(run())
