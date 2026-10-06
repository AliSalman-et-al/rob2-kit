"""Measure retained inputs and native receipts without inference or workspace writes."""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
NATIVE = ROOT / 'docs/evaluation/2026-10-04-gupta-fork-continuation'
PANEL = ROOT / 'docs/evaluation/2026-10-04-citation-fidelity-response'

def size(text):
    return {'characters': len(text), 'utf8_bytes': len(text.encode()),
            'sha256': hashlib.sha256(text.encode()).hexdigest()}

reviews = []
for line in (NATIVE / 'turn-1.jsonl').read_text().splitlines():
    row = json.loads(line)
    item = row.get('item', {})
    if row['type'] != 'item.completed' or item.get('tool') != 'review_trial':
        continue
    data = item['result']['structured_content']['data']
    page = data['review_page']
    fragment = page.get('fragment') or ''
    delivered = json.dumps(data, ensure_ascii=False)
    reviews.append({
        'arguments': item['arguments'], 'mode': page['mode'], 'complete': page['complete'],
        'offset': page.get('offset'), 'total': page.get('total'),
        'next_cursor': page.get('next_cursor'), 'fragment': size(fragment),
        'contains_count_text': '13/86' in delivered and '13/94' in delivered,
        'contains_differential_question_id': 'sq:measurement:differential' in delivered,
        'contains_correct_source_handle': 'eh_49ac77da50b0bd19' in delivered,
    })
packet = json.loads((OUT / 'deterministic-measurement-input.json').read_text())
text = (OUT / 'deterministic-measurement-input.json').read_text()
panel = (PANEL / 'panel-input.txt').read_text()
a = panel[panel.index('Item A ('):panel.index('Item B (')]
assert len(packet['claims']) == 3
assert all('13/86' not in s['numbered_text'] and '13/94' not in s['numbered_text']
           for s in packet['cited_spans'])
assert any(r['contains_count_text'] for r in reviews)
d4 = next(r for r in reviews if r['arguments'].get('domain_id') == 'domain:measurement')
assert not d4['contains_differential_question_id'] and not d4['contains_count_text']
assert d4['next_cursor'] and not d4['complete']
summary = {
    'model_calls_this_turn': 0,
    'panel_input': size(panel), 'panel_item_a': size(a),
    'panel_actual_input_tokens': 16807, 'panel_actual_output_tokens': 663,
    'panel_model_responses': 1, 'panel_tools': 0,
    'native_review_receipts': reviews,
    'native_actual_input_tokens': 765107, 'native_cached_input_tokens': 683520,
    'native_actual_uncached_input_tokens': 81587,
    'native_output_tokens': 2476, 'native_tools': 13, 'native_model_turns': 1,
    'prototype_input': size(text), 'prototype_claims': len(packet['claims']),
    'prototype_unique_cited_spans': len(packet['cited_spans']),
    'prototype_input_tokens': 'Not measured: no model call and exact launcher tokenizer unavailable.',
    'budget_sensitivity_estimates': {
        'characters_divided_by_four': round(len(text) / 4),
        'scaled_from_observed_panel_bytes_per_input_token': round(len(text.encode()) * 16807 / len(panel.encode())),
        'warning': 'Sizing heuristics, not tokenizer counts. Panel telemetry includes its instruction/host overhead; model vocabulary and overhead differ.'},
    'proposed_incremental_calls': 1, 'proposed_tools': 0,
    'correct_source_in_export': False,
    'limitation': 'Only answer-level citation bindings, no clause alignment or automatic alternative-source completeness. Non-narrative or missing exact linkage is rejected. Role annotations are host assertions.',
    'observable_difference': 'Focused clause plus operator-curated correct alternative co-located in the panel. Native D4 incomplete prefix omitted the target warrant and its complete pair; D3 prefix separately contained correct-source counts. No equivalent controlled comparison or evidence for anchoring/capacity causation.'
}
(OUT / 'comparison.json').write_text(json.dumps(summary, indent=2) + '\n')
print(json.dumps({k: summary[k] for k in ['prototype_input','prototype_claims','prototype_unique_cited_spans','budget_sensitivity_estimates']}, indent=2))
