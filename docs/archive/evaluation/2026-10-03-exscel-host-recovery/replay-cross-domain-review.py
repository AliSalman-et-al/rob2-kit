import json,hashlib
from pathlib import Path
from rob2_kit.application.trials import _review_domain_findings
from rob2_kit.interfaces.mcp import server
out=Path('docs/evaluation/2026-10-03-exscel-host-recovery');root=Path('../diagnostics/frozen-exscel-bd92ec8/workspace').resolve()
bundle=next(out.glob('*.rob2.zip'));digest=hashlib.sha256(bundle.read_bytes()).hexdigest()
state=json.loads((out/'frozen-final-state.json').read_text())
rows=[json.loads(l) for l in (out/'turn-0.events.jsonl').read_text().splitlines()]
snap=next(r['item']['result']['structured_content'] for r in rows if r.get('type')=='item.completed' and r.get('item',{}).get('id')=='item_35')
snap['data']['domain_findings']=_review_domain_findings(root,state,'exscel')
from rob2_kit.application.source_handles import public_source_references
snap=public_source_references(snap)
before=server._review_summary(snap,'0'*64,'0'*32,keep_previews=False,keep_missing=True,keep_evidence=True,keep_result=True,preview_chars=0)
after=server._project_review_trial(snap,cursor=None,selector=None,root=root,persist=False)
for name,value in [('before',before),('after',after)]:
 (out/f'cross-domain-review-{name}.json').write_text(json.dumps(value,indent=2))
 print(name,server._review_transport_bytes(value))
 for d in value['data']['domain_findings']:
  for a in d['answers']:
   if a['question_id'] in ['sq:missing:evidence-unbiased','sq:selection:multiple-analyses']:print(a['question_id'],a.get('warrant'),a.get('unknowns'))
assert digest==hashlib.sha256(bundle.read_bytes()).hexdigest()
assert server._review_transport_bytes(after)<=24000
(out/'cross-domain-replay-metadata.json').write_text(json.dumps({'frozen_bundle_sha256':digest,'frozen_bundle_unchanged':True,'before_bytes':server._review_transport_bytes(before),'after_bytes':server._review_transport_bytes(after),'replay':'same frozen canonical records and evidence catalog; actual item_35 envelope; projection only; persist=False; no inference'},indent=2))
for n in [400,320,240,200,160,100]:
 x=server._validate_response('review_trial',server._review_summary(snap,'0'*64,'0'*32,keep_previews=False,keep_missing=True,keep_evidence=True,keep_result=False,preview_chars=n));print(n,server._review_transport_bytes(x))
