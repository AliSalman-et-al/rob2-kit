import copy
import hashlib
import json
import sqlite3
from pathlib import Path
from rob2_kit.application.evidence import _evidence_catalog
from rob2_kit.logic import evaluate_domain

root = Path('../diagnostics/frozen-an-5a3e580/an-2021').resolve()
out = Path('docs/evaluation/2026-10-02-frozen-an-5a3e580')
p = out / 'an-2021'
raw = (root / 'events.jsonl').read_bytes()
events = [json.loads(line) for line in raw.decode().splitlines()]
sanitized = copy.deepcopy(events)
omitted = []
for ordinal, event in enumerate(sanitized):
    result = event.get('item', {}).get('result') or {}
    for index, block in enumerate(result.get('content', [])):
        if block.get('type') == 'image':
            digest = hashlib.sha256(block['data'].encode()).hexdigest()
            omitted.append({'event_ordinal': ordinal, 'content_index': index, 'base64_sha256': digest})
            result['content'][index] = {'type': 'omitted_image', 'base64_sha256': digest,
                'base64_character_count': len(block['data']),
                'qualification': 'Original image retained in local raw events; receipts unchanged.'}
serialized = ''.join(json.dumps(e) + '\n' for e in sanitized).encode()
(p / 'events.sanitized.jsonl').write_bytes(serialized)
(p / 'events.jsonl').unlink()
(out / 'event-provenance.json').write_text(json.dumps({'raw_events_sha256': hashlib.sha256(raw).hexdigest(),
    'sanitized_events_sha256': hashlib.sha256(serialized).hexdigest(),
    'omitted_images': omitted, 'raw_local_path': str(root / 'events.jsonl')}, indent=2) + '\n')
actions = []; saves = []; deliveries = []
for n, event in enumerate(sanitized):
    i = event.get('item', {})
    if event['type'] != 'item.completed' or i.get('type') != 'mcp_tool_call':
        continue
    actions.append({'event_ordinal': n, 'tool': i.get('tool'), 'arguments': i.get('arguments'), 'status': i.get('status')})
    if i.get('tool') == 'save_domain_judgment':
        saves.append({'event_ordinal': n, 'arguments': i['arguments'], 'status': i['status'], 'result': i.get('result'), 'error': i.get('error')})
    if i.get('tool') == 'read_pages':
        v = (i.get('result') or {}).get('structured_content') or {}
        deliveries.append({'event_ordinal': n, 'arguments': i['arguments'], 'result': v})
(p / 'submissions.json').write_text(json.dumps(saves, indent=2) + '\n')
(p / 'tool-actions.json').write_text(json.dumps(actions, indent=2) + '\n')
(p / 'report-deliveries.json').write_text(json.dumps(deliveries, indent=2) + '\n')
with sqlite3.connect(f'file:{root}/workspace/.rob2-kit/canonical.sqlite3?mode=ro', uri=True) as c:
    state = json.loads(c.execute('select payload from workflow_head').fetchone()[0])
record = state['domain_records'].get('an-2021:domain:deviations')
(p / 'final-domain-record.json').write_text(json.dumps(record, indent=2) + '\n')
last = saves[-1]['arguments']; answers = {a['question_id']: a['answer'] for a in last['answers']}
mapping = evaluate_domain('domain:deviations', answers)
(p / 'answer-only-mapping.json').write_text(json.dumps({'evaluation': mapping.model_dump(mode='json'),
    'production_checkpoint_exists': record is not None,
    'qualification': 'Last rejected draft enum mapping only; not accepted, validated scientifically, or scored.'}, indent=2) + '\n')
handles = {b['evidence'] for a in last['answers'] for b in a.get('bases', [])}
handles |= {h for a in last['answers'] for point in a.get('counterevidence', []) for h in point['evidence']}
catalog = _evidence_catalog(root / 'workspace', 'an-2021')
selected = {k: v for k, v in catalog.items() if v['handle'] in handles}
assert len(selected) == len(handles)
(p / 'selected-evidence.json').write_text(json.dumps(selected, indent=2) + '\n')
run = json.loads((p / 'run.json').read_text())
assert run['code_sha'] == '5a3e58034c57ef6c19a64fceeb3ced84edd30263'
usage = json.loads((p / 'durable-token-usage-records.json').read_text())
assert run['usage']['input_tokens'] == sum(r['usage']['input_tokens'] for r in usage)
print('record', record, 'mapping', mapping.model_dump(mode='json'))
print('uncached', run['usage']['input_tokens'] - run['usage']['cached_input_tokens'])
print('page11 evidence', json.dumps([v for v in selected.values() if 'intensity' in json.dumps(v).lower()], indent=2))
