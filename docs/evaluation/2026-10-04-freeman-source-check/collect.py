"""Collect the frozen failed invocation; never synthesize reviewer findings or retry."""
from __future__ import annotations

import base64
import hashlib
import json
import shutil
from pathlib import Path

from rob2_kit.application._state import _state
from scripts.export_factual_audit import native_review_schema

R = Path(__file__).resolve().parent
D = R.parents[2].parent / 'diagnostics/freeman-source-check-20261004'


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
    packet = json.loads((R / 'packet.json').read_text())
    assert run['effective_model'] == [{'model': 'gpt-6-luna', 'effort': 'medium'}]
    assert run['exit_code'] == 1 and run['tool_calls'] == run['provider_responses'] == 0
    assert not (D / 'request/response.json').exists()
    events = [json.loads(line) for line in (D / 'events.jsonl').read_text().splitlines()]
    failure = next(row['error'] for row in events if row['type'] == 'turn.failed')
    detail = json.loads(failure['message'])
    assert detail['error']['code'] == 'invalid_json_schema'
    write(R / 'failure.json', {'native_turn_error': detail, 'events': events})
    for name in ('run.json', 'effective-model.json', 'durable-token-usage-records.json', 'answer-freeze.json'):
        shutil.copyfile(D / name, R / name)
    session = Path(run['native_sessions'][0])
    rows = [json.loads(line) for line in session.read_text().splitlines()]
    texts = []
    images = []
    developer = []
    token_counts = []
    for row in rows:
        payload = row.get('payload', {})
        if row['type'] == 'response_item' and payload.get('type') == 'message':
            for item in payload.get('content', []):
                if payload.get('role') == 'developer' and item.get('type') == 'input_text':
                    developer.append({'characters': len(item['text']), 'sha256': hashlib.sha256(item['text'].encode()).hexdigest()})
                elif payload.get('role') == 'user' and item.get('type') == 'input_text':
                    texts.append(item['text'])
                elif payload.get('role') == 'user' and item.get('type') == 'input_image':
                    url = item['image_url']
                    assert url.startswith('data:image/png;base64,')
                    pixels = base64.b64decode(url.split(',', 1)[1], validate=True)
                    images.append({'png_sha256': hashlib.sha256(pixels).hexdigest(), 'width': int.from_bytes(pixels[16:20], 'big'), 'height': int.from_bytes(pixels[20:24], 'big'), 'channel': 'native initial input_image'})
        if row['type'] == 'event_msg' and payload.get('type') == 'token_count':
            token_counts.append(payload.get('info'))
    prompt = (D / 'request/prompt.txt').read_text(encoding='utf-8')
    assert prompt in texts
    expected = json.loads((D / 'request/request.json').read_text())['images']
    assert [image['png_sha256'] for image in images] == [image['png_sha256'] for image in expected]
    native_record = {'packet_text_exactly_in_native_user_input': True, 'prompt_sha256': sha(D / 'request/prompt.txt'), 'claims': len(packet['claims']), 'full_warrants_preserved': True, 'all_unknowns_counterclaims_original_citation_bindings_preserved': True, 'images': images, 'developer_blocks_hashes': developer, 'source_followup_calls': [], 'provider_completed_delivery_or_comprehension_not_established': True, 'native_session_sha256': sha(session)}
    write(R / 'delivery-validation.json', native_record)
    write(R / 'contract-receipt.json', {'reviewer_output_present': False, 'advisory_validation': 'not possible: no reviewer response', 'native_schema_rejected': True, 'semantic_findings': [], 'assessment_mutated': False, 'semantic_metrics': {'recall': None, 'false_positives': None, 'citation_validity': None, 'inference_preservation': None}, 'reason': 'Native HTTP400 invalid_json_schema prevented scientific review. Do not score absent findings as reviewer misses or successful restraint.'})
    write(R / 'usage-receipt.json', {'native_invocations': 1, 'elapsed_seconds': run['elapsed_seconds'], 'completed_provider_responses': 0, 'durable_token_usage_records': 0, 'token_count_info': token_counts, 'measured_completed_input_tokens': None, 'measured_completed_output_tokens': None, 'cost': None, 'warning': 'run.json sums an empty durable-record set to zero; those zeros are not observed token usage or a zero billing/cost claim.'})
    write(R / 'postfreeze-native-schema.json', native_review_schema())
    write(R / 'preservation.json', {'protected_files': len(json.loads((D / 'protected.json').read_text())), 'all_original_and_staged_protected_hashes_unchanged': True, 'answer_freeze_unchanged': True, 'original_revision': manifest['original_revision'], 'staged_revision': _state(Path(manifest['workspace']))['revision'], 'scientific_author_feedback': False, 'paid_retry': False, 'frozen_original_schema_sha256': sha(R / 'response-schema.json'), 'corrected_schema_not_submitted': True})
    write(R / 'stderr-provenance.json', {'path': str(D / 'stderr.log'), 'sha256': sha(D / 'stderr.log'), 'privacy': 'Raw account-bearing stderr stays private; no credential contents read/copied.'})
    print(json.dumps({'failed_invocations': 1, 'full_claims_in_client_input': len(packet['claims']), 'native_initial_images': len(images), 'scientific_metrics': 'unavailable', 'canonical_unchanged': True}))


if __name__ == '__main__':
    main()
