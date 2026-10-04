"""Preserve full frozen review, source binding failures and native delivery/usage."""
from __future__ import annotations

import base64
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

from rob2_kit.application._state import _state
from rob2_kit.application.source_check import SourceCheckReport, _text_values

R = Path(__file__).resolve().parent
D = R.parents[2].parent / 'diagnostics/freeman-source-check-recovery-20261004'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main():
    manifest = json.loads((R / 'manifest.json').read_text())
    for name, digest in json.loads((D / 'answer-freeze.json').read_text()).items():
        assert sha(Path(name)) == digest
    for name, digest in json.loads((D / 'protected.json').read_text()).items():
        assert sha(Path(name)) == digest
    run = json.loads((D / 'run.json').read_text())
    assert run['exit_code'] == 0 and run['effective_model'] == [{'model': 'gpt-6-luna', 'effort': 'medium'}]
    for name in ('run.json', 'effective-model.json', 'durable-token-usage-records.json', 'answer-freeze.json'):
        shutil.copyfile(D / name, R / name)
    shutil.copyfile(D / 'request/response.json', R / 'response.json')
    response = SourceCheckReport.model_validate_json((R / 'response.json').read_bytes())
    packet = json.loads((R / 'packet.json').read_text())
    assert response.snapshot_identity == packet['snapshot_identity']
    claims = {item['claim_id']: item for item in packet['claims']}
    routing = {item['claim_id']: item['question_id'] for item in json.loads((R / 'request.json').read_text())['assessor_routing_not_model_input']}
    binding = []
    sources = {source['id']: source for trial in _state(Path(manifest['workspace']))['batch']['trials'] for source in trial['sources']}
    with sqlite3.connect(f"file:{manifest['workspace']}/.rob2-kit/derivative.sqlite3?mode=ro", uri=True) as connection:
        for number, finding in enumerate(response.findings, 1):
            values = _text_values(claims[finding.claim_id][finding.field])
            row = {'finding': number, 'question_id_for_parent_only': routing[finding.claim_id], 'field': finding.field, 'classification': finding.classification, 'exact_clause_in_single_saved_entry': any(finding.clause in value for value in values), 'references': []}
            for reference in finding.references:
                location = reference.location.model_dump(mode='json')
                assert 'source_id' in location, 'Retain and explicitly audit any future visual ref'
                source = next(source for identity, source in sources.items() if 'sh_' + identity.removeprefix('source_')[:16] == location['source_id'])
                page = connection.execute('SELECT text FROM pages WHERE source_id=? AND page=?', (source['id'], location['page'])).fetchone()[0].splitlines()
                exact = '\n'.join(page[location['start_line']-1:location['end_line']])
                original_ids = {basis.get('evidence') for basis in claims[finding.claim_id]['citations']}
                original = any(span['evidence_identity'] in original_ids and span['kind']=='narrative' and span['source_id']==location['source_id'] and span['page']==location['page'] and span['start_line']<=location['start_line'] and span['end_line']>=location['end_line'] for span in packet['cited_spans'])
                row['references'].append({'location': location, 'reported_quote': reference.quote, 'exact_source_window': exact, 'numbered_source_window': '\n'.join(f'{i}|{text}' for i,text in enumerate(page,1) if location['start_line']<=i<=location['end_line']), 'quote_equals_complete_exact_window': reference.quote == exact, 'quote_is_verbatim_after_whitespace_normalization': ' '.join((reference.quote or '').split()) in ' '.join(exact.split()), 'inside_own_original_narrative_citation': original, 'source_sha256': source['sha256']})
            binding.append(row)
    refs = [reference for row in binding for reference in row['references']]
    write(R / 'all-findings-source-audit.json', binding)
    write(R / 'binding-summary.json', {'findings': len(binding), 'claim_ids_covered': len({finding.claim_id for finding in response.findings}), 'all_claims': len(claims), 'references': len(refs), 'complete_exact_quotes': sum(ref['quote_equals_complete_exact_window'] for ref in refs), 'whitespace_normalized_verbatim_excerpts': sum(ref['quote_is_verbatim_after_whitespace_normalization'] for ref in refs), 'invalid_joined_saved_entries': [row['finding'] for row in binding if not row['exact_clause_in_single_saved_entry']], 'visual_reference_objects': 0, 'quote_normalization_is_diagnostic_only': True})
    rows = [json.loads(line) for line in Path(run['native_sessions'][0]).read_text().splitlines()]
    images = []
    texts = []
    for row in rows:
        payload = row.get('payload', {})
        if row['type']=='response_item' and payload.get('type')=='message' and payload.get('role')=='user':
            for item in payload.get('content', []):
                if item.get('type')=='input_text':
                    texts.append(item['text'])
                elif item.get('type')=='input_image':
                    pixels = base64.b64decode(item['image_url'].split(',',1)[1], validate=True)
                    images.append({'sha256': hashlib.sha256(pixels).hexdigest(), 'width': int.from_bytes(pixels[16:20],'big'), 'height': int.from_bytes(pixels[20:24],'big'), 'channel': 'native initial input_image'})
    assert (D / 'request/prompt.txt').read_text(encoding='utf-8') in texts
    assert [image['sha256'] for image in images] == [image['png_sha256'] for image in json.loads((R / 'request.json').read_text())['images']]
    native = []
    for line in (D / 'events.jsonl').read_text().splitlines():
        row = json.loads(line)
        item = row.get('item', {})
        if row['type']=='item.completed' and item.get('type')=='mcp_tool_call':
            result = item.get('result') or {}
            content = result.get('content', [])
            native.append({'tool': item['tool'], 'arguments': item.get('arguments'), 'result': result.get('structured_content') or result, 'returned_image_count': sum(block.get('type')=='image' for block in content)})
    write(R / 'native-receipts.json', native)
    write(R / 'delivery-validation.json', {'exact_full_prompt_in_native_user_input': True, 'claims': 4, 'images': images, 'source_calls': len(native), 'fresh_render_calls': sum(row['tool']=='render_page' for row in native), 'full_source_followup_available': True, 'completed_provider_responses': run['provider_responses'], 'provider_schema_acceptance_observed': True, 'comprehension_not_inferred_from_delivery': True, 'session_sha256': sha(Path(run['native_sessions'][0]))})
    write(R / 'preservation.json', {'protected_files': len(json.loads((D / 'protected.json').read_text())), 'original_failed_attempt_and_source_assessment_unchanged': True, 'answer_freeze_unchanged': True, 'canonical_revision': _state(Path(manifest['workspace']))['revision'], 'author_feedback': False, 'canonical_edits': False, 'reviewer_retries': False})
    write(R / 'stderr-provenance.json', {'sha256': sha(D / 'stderr.log'), 'raw_stderr_stays_private': True})
    print((R / 'binding-summary.json').read_text())


if __name__ == '__main__':
    main()
