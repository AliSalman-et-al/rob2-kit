from pathlib import Path
import json,sqlite3,hashlib,tempfile,shutil,sys
repo=Path.cwd();sys.path.insert(0,str(repo/'src'))
from rob2_kit.application.domains import get_domain_context
from rob2_kit.application._state import _state,_commit
out=repo/'docs/evaluation/2026-10-03-contrast-boundary-set';out.mkdir(exist_ok=True)
b=Path('/home/ali/Documents/Code/rob2-kit-benchmark/benchmark-luna6-medium-2026-10-01/cases');corpus=b.parent.parent/'rob2-meta-set-full-2026-09-29/trials'
records={}
for case in ['getgoal-f1-2013','stopdapt-2','exscel']:
 p=b/case;hashes={n:hashlib.sha256((p/'.rob2-kit'/n).read_bytes()).hexdigest() for n in ['canonical.sqlite3','derivative.sqlite3']}
 with sqlite3.connect(f'file:{p}/.rob2-kit/canonical.sqlite3?mode=ro',uri=True) as c:
  s=json.loads(c.execute('select payload from workflow_head').fetchone()[0]);r=s['domain_records'][case+':domain:missing'];bindings=[]
  for a in r['answers']:
   for basis in a['bases']:
    if basis.get('evidence'):
     row=c.execute('select payload from canonical_records where identity=?',(basis['evidence'],)).fetchone();bindings.append(json.loads(row[0]))
 sources=s['batch']['trials'][0]['sources'];verified=[]
 for src in sources:
  raw=corpus/case/src['logical_path'];item=dict(src)
  item['raw_available']=raw.is_file();item['raw_path']=str(raw)
  if raw.is_file():item['verified_raw_identity']='sha256:'+hashlib.sha256(raw.read_bytes()).hexdigest();assert item['verified_raw_identity']==src['sha256']
  verified.append(item)
 pages=[]
 with sqlite3.connect(f'file:{p}/.rob2-kit/derivative.sqlite3?mode=ro',uri=True) as d:
  for e in bindings:
   if e.get('kind')=='narrative':
    row=d.execute('select text from pages where source_id=? and page=?',(e['source_id'],e['page'])).fetchone()
    if row:pages.append({'source_id':e['source_id'],'page':e['page'],'numbered_text':'\n'.join(f'{i}|{line}' for i,line in enumerate(row[0].splitlines(),1))})
 with tempfile.TemporaryDirectory() as tmp:
  copy=Path(tmp)/'workspace';shutil.copytree(p,copy);original=_state(copy);projected=json.loads(json.dumps(original));projected['phase']='assessment';projected['domain_records']={k:v for k,v in projected['domain_records'].items() if v['domain_id'] in ['domain:randomization','domain:deviations']};projected['trial_dispositions']={case:'pending'};projected['review']=None;_commit(copy,projected,original['revision'])
  for src in verified:
   if src['raw_available']:
    dest=copy/'.rob2-kit/sources'/case/(src['id']+'.bin');dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src['raw_path'],dest)
  try:context=get_domain_context(copy,case,'domain:missing')
  except Exception as error:context={'offline_projection_error':type(error).__name__,'detail':str(error),'qualification':'Historical copy/source recovery limitation; not an inference run.'}
 records[case]={'original_workspace':str(p),'original_database_sha256':hashes,'approved_result':s['proposal']['payload']['results'][0],'canonical_d3':r,'source_bindings':bindings,'verified_source_inventory':verified,'cited_narrative_pages':pages,'current_context_first_page':context,'reference_full_scope':'unknown; approved target/report relation is not independent human reference matching'}
 assert all(hashlib.sha256((p/'.rob2-kit'/n).read_bytes()).hexdigest()==h for n,h in hashes.items())
(out/'retained-source-and-context-evidence.json').write_text(json.dumps(records,indent=2)+'\n')
shutil.copyfile(Path(__file__),out/'audit-boundary-set.py')
for case,r in records.items():
 print(case)
 print('bindings',[(e.get('kind'),e.get('source_id'),e.get('page'),e.get('start_line'),e.get('end_line')) for e in r['source_bindings']])
 print('rawavailable',[(s['logical_path'],s['raw_available']) for s in r['verified_source_inventory']])
 print('contextkeys',list(r['current_context_first_page'].get('data',{})))
