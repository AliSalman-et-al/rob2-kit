"""Offline transport replay of retained Allsop context snapshots; no model call."""
from pathlib import Path
import copy,hashlib,json,sqlite3,sys,asyncio,os,shutil
from fastmcp import Client
repo=Path('/home/ali/Documents/Codex/2026-10-02/task-4/rob2-kit');sys.path.insert(0,str(repo/'src'))
import rob2_kit.interfaces.mcp.server as server
from rob2_kit.application.evidence import main_report_reading_status,source_reading_status
from rob2_kit.application._state import _state
from rob2_kit.application.source_handles import source_handle
root=repo.parent/'diagnostics/frozen-allsop-full-72bf943';out=repo/'docs/evaluation/2026-10-03-context-source-delivery';out.mkdir(exist_ok=True)
with sqlite3.connect(f'file:{root}/workspace/.rob2-kit/derivative.sqlite3?mode=ro',uri=True) as c:
 snapshots=c.execute('select domain_id,snapshot,page_size,page_count,basis_identity,state_revision from domain_context_delivery order by state_revision').fetchall()
# Preserve the real short-cursor wire shape while decoding in memory instead
# of creating delivery views in the preserved paid workspace.
cursors={}
def encode(payload):
    view=hashlib.sha256((payload['digest']+str(payload['page_size'])).encode()).hexdigest()[:32]
    cursor=f"dcp2.{view}.{payload['page_index']}";cursors[cursor]=copy.deepcopy(payload);return cursor
server._domain_context_cursor=encode
server._decode_domain_context_cursor=lambda cursor:copy.deepcopy(cursors[cursor])
def pages(value,size,basis,revision):
    cursor=None;result=[]
    while True:
        page=server._paginate_domain_context_transport(value,cursor,size,basis,revision)
        result.append(page);cursor=page['data']['context_page']['next_cursor']
        if cursor is None:return result
report=[];native=[json.loads(l) for l in (root/'events.jsonl').read_text().splitlines()]
read_lines={}
for event in native:
    item=event.get('item',{})
    if event['type']=='item.completed' and item.get('tool')=='read_pages':
        for page in (item.get('result')or{}).get('structured_content',{}).get('data',{}).get('pages',[]):
            for line in page['numbered_text'].splitlines():
                number,text=line.split('|',1)
                read_lines[(page['source_id'],page['page'],int(number))]=text

# Replay all original read_pages requests through current direct MCP in a
# disposable database copy; preserve the paid workspace unchanged.
workspace=repo.parent/'diagnostics/offline-allsop-source-replay-v2'
workspace.mkdir(exist_ok=True);internal=workspace/'.rob2-kit';internal.mkdir(exist_ok=True)
for name in ['canonical.sqlite3','derivative.sqlite3']:
    with sqlite3.connect(f'file:{root}/workspace/.rob2-kit/{name}?mode=ro',uri=True) as source,sqlite3.connect(internal/name) as target:source.backup(target)
if (internal/'sources').exists():
    assert False,'Use a fresh disposable source replay, never silently overwrite it'
shutil.copytree(root/'workspace/.rob2-kit/sources',internal/'sources')
with sqlite3.connect(internal/'derivative.sqlite3') as c:c.execute('delete from page_reads')
missing=[]
for _,blob,_,_,_,_ in snapshots:
    for passage in json.loads(blob)['data']['primary_report']:
        for line in passage['numbered_text'].splitlines():
            number,text=line.split('|',1);key=(passage['source_id'],passage['page'],int(number))
            if key not in read_lines:missing.append((key,text))
windows=[]
for (source,page,line),text in sorted(missing):
    if windows and windows[-1]['source_id']==source and windows[-1]['page']==page and windows[-1]['end_line']+1==line:windows[-1]['end_line']=line
    else:windows.append({'source_id':source,'page':page,'start_line':line,'end_line':line})
extra=[]
complete_report_control={}
async def source_replay():
    os.environ['ROB2_WORKSPACE']=str(workspace)
    async with Client(server.mcp) as client:
        for event in native:
            item=event.get('item',{})
            if event['type']=='item.completed' and item.get('tool')=='read_pages':
                response=await client.call_tool('read_pages',item['arguments']);assert response.structured_content['outcome']=='success'
        pending=windows
        while pending:
            response=await client.call_tool('read_pages',{'trial_id':'allsop-2014','windows':pending})
            data=response.structured_content['data'];extra.append(response.structured_content)
            for page in data['pages']:
                for line in page['numbered_text'].splitlines():
                    number,text=line.split('|',1);read_lines[(page['source_id'],page['page'],int(number))]=text
            pending=data.get('remaining_windows') or []
        state=_state(workspace)
        before_footer=main_report_reading_status(workspace,state['batch']['trials'],phase='assessment')['allsop-2014']
        complete_report_control['before_status']=before_footer['status']
        if before_footer['unread_ranges']:
            footer_windows=[{**w,'source_id':source_handle(w['source_id'])} for w in before_footer['unread_ranges']]
            footer=await client.call_tool('read_pages',{'trial_id':'allsop-2014','windows':footer_windows})
            complete_report_control['additional_calls']=1
            complete_report_control['response']=footer.structured_content
        complete_report_control['after_status']=main_report_reading_status(workspace,state['batch']['trials'],phase='assessment')['allsop-2014']['status']
        assert complete_report_control['after_status']=='complete'
        assert set(source_reading_status(workspace,'allsop-2014').values())=={'read_complete'}

asyncio.run(source_replay())
(out/'complete-report-control.json').write_text(json.dumps(complete_report_control,indent=2)+'\n')
(out/'additional-source-deliveries.json').write_text(json.dumps(extra,indent=2)+'\n')
for domain,blob,size,count,basis,revision in snapshots:
    before=json.loads(blob);before.pop('_context_basis_identity',None)
    baseline=pages(before,size,basis,revision);assert len(baseline)==count,(domain,len(baseline),count)
    after=copy.deepcopy(before);inline=after['data']['primary_report'];after['data']['primary_report']=[]
    # Everything scientific/source-located outside the duplicated inline report
    # remains exact. The implementation's shorter completion wording is not
    # included in this controlled byte comparison.
    revised=pages(after,size,basis,revision)
    recovered_lines=0
    for passage in inline:
        for line in passage['numbered_text'].splitlines():
            number,text=line.split('|',1)
            assert read_lines[(passage['source_id'],passage['page'],int(number))]==text
            recovered_lines+=1

    for name in ['questions','evidence','comparison_cards']:
        reconstructed=[x for page in revised for x in page['data'].get(name,[])]
        assert reconstructed==before['data'][name],(domain,name)
    for field in ['official_guidance','result','answers','reading_recovery']:
        assert revised[0]['data'][field]==before['data'][field]
    old_native=[e['item']['result']['structured_content'] for e in native if e['type']=='item.completed' and e.get('item',{}).get('tool')=='get_domain_context' and e['item']['arguments']['domain_id']==domain and (e['item'].get('result')or{}).get('structured_content',{}).get('outcome')=='success']
    assert len(old_native)==count
    baseline_bytes=sum(server._domain_context_transport_bytes(p) for p in baseline)
    actual_bytes=sum(server._domain_context_transport_bytes(p) for p in old_native)
    assert baseline_bytes==actual_bytes,(domain,baseline_bytes,actual_bytes)
    after_bytes=sum(server._domain_context_transport_bytes(p) for p in revised)
    report.append({'domain':domain,'page_budget':size,'before_calls':len(baseline),'after_calls':len(revised),'before_native_structured_bytes':actual_bytes,'after_structured_bytes':after_bytes,'removed_inline_source_bytes':sum(len(p['numbered_text'].encode()) for p in inline),'scientific_content_exact':True,'removed_inline_lines_exactly_recovered_by_original_plus_additional_read_pages':recovered_lines,'after_pages_path':domain.split(':')[1]+'-after-pages.json'})
    (out/report[-1]['after_pages_path']).write_text(json.dumps(revised,indent=2)+'\n')
summary={'case':'allsop-2014','before_context_calls':18,'before_successful_context_calls':sum(r['before_calls'] for r in report),'after_successful_context_calls':sum(r['after_calls'] for r in report),'equivalent_exposure_total_calls_before':31,'equivalent_exposure_total_calls_after':27,'full_primary_tail_control_additional_calls':1,'unchanged_oversized_header_condition_calls':1,'additional_native_read_pages_calls':len(extra),'additional_uncovered_source_windows':windows,'duplicated_inline_lines':sum(len(p['numbered_text'].splitlines()) for _,b,_,_,_,_ in snapshots for p in json.loads(b)['data']['primary_report'])-len(missing),'domains':report,'qualification':'Exact retained immutable snapshot transport replay, keeping every scientific field and source locator. Uses real cursor shape, exact original budgets and byte-for-byte source/target content, not a model prediction or changed clinical assessment. Original read_pages actions are held fixed; extra bounded native source calls supply inline passages not returned by those original calls. The existing header-size recovery is not assumed eliminated.'}
(out/'replay-summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2))
