"""Freeze the authorized production Freeman source-check request; no inference."""
from __future__ import annotations

import hashlib
import io
import json
import shutil
import sqlite3
import subprocess
import tarfile
from pathlib import Path

from rob2_kit.application._state import _state
from rob2_kit.application.evidence import _verified_source_projections
from scripts.diagnostic_evidence_preflight import check_manifest
from scripts.export_factual_audit import prepare_native_review

R = Path(__file__).resolve().parent
REPO = R.parents[2]
D = REPO.parent / 'diagnostics/freeman-source-check-20261004'
ORIGINAL = REPO.parent / 'diagnostics/freeman-native-d3/workspace'
HOME = REPO.parent / 'diagnostics/freeman-native-d3/home'
CODE_BENCH = Path('/home/ali/Documents/Code/rob2-kit-benchmark')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main():
    assert not D.exists() and not (R / 'manifest.json').exists(), 'Preserve frozen preparation'
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip() == '22e84f3fca0aba63639e35684446e7aa91098ca0'
    D.mkdir(parents=True)
    shutil.copytree(ORIGINAL, D / 'workspace')
    code = D / 'code'
    code.mkdir()
    archive = subprocess.check_output(['git', 'archive', 'HEAD'], cwd=REPO)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(code, filter='data')
    work = D / 'workspace'
    state = _state(work)
    source_inventory = [source for trial in state['batch']['trials'] for source in trial['sources']]
    for source in source_inventory:
        original_pdf = CODE_BENCH / 'rob2-meta-set-full-2026-09-29/trials/freeman-2020' / source['logical_path']
        assert sha(original_pdf) == source['sha256'].removeprefix('sha256:'), original_pdf
    write(R / 'source-provenance.json', source_inventory)
    declared = prepare_native_review(work, 'freeman-2020', 'domain:missing', D / 'request', assessor_model='gpt-6-luna', assessor_effort='medium', reviewer_model='gpt-6-luna', reviewer_effort='medium')
    command = declared['command']
    # Only the code path changes to the byte-identical frozen implementation.
    old = 'mcp_servers.rob2.env.PYTHONPATH=' + json.dumps(str(REPO / 'src'), separators=(',', ':'))
    command[command.index(old)] = 'mcp_servers.rob2.env.PYTHONPATH=' + json.dumps(str(code / 'src'))
    write(D / 'command.json', command)
    for name in ('packet.json', 'response-schema.json', 'instructions.md', 'prompt.txt', 'request.json'):
        shutil.copyfile(D / 'request' / name, R / name)
    write(R / 'command.json', command)
    # Full availability stays private, rather than adding operator-selected repair pages.
    block = bytearray()
    windows = []
    projections = _verified_source_projections(work, {('freeman-2020', source['id']) for source in source_inventory})
    for source in source_inventory:
        pages = projections[('freeman-2020', source['id'])][1]
        for page, text in enumerate(pages, 1):
            lines = text.splitlines()
            if not lines:
                continue
            block.extend(f"Source {source['id']} page {page}\n".encode())
            start = len(block)
            numbered = '\n'.join(f'{i}|{line}' for i, line in enumerate(lines, 1)).encode()
            block.extend(numbered)
            end = len(block)
            block.extend(b'\n\n')
            windows.append({'source_identity': source['id'], 'page': page, 'start_line': 1, 'end_line': len(lines), 'input_start_byte': start, 'input_end_byte': end, 'text_sha256': hashlib.sha256(numbered).hexdigest()})
    images = []
    for image in declared['images']:
        pixels = Path(image['path']).read_bytes()
        span = next(item for item in json.loads((D / 'request/packet.json').read_text())['cited_spans'] if item['evidence_identity'] == image['evidence_identity'])
        start = len(block)
        block.extend(pixels)
        images.append({'source_identity': span['render']['source_id'], 'page': span['render']['page'], 'png_sha256': image['png_sha256'], 'width': int.from_bytes(pixels[16:20], 'big'), 'height': int.from_bytes(pixels[20:24], 'big'), 'input_start_byte': start, 'input_end_byte': len(block)})
    availability = D / 'availability.bin'
    availability.write_bytes(block)
    evidence_manifest = {'research_question': 'Can a production source-check review check all full saved claims with faithful attribution and preserved inference?', 'input_sha256': sha(availability), 'required_windows': [{key: value for key, value in item.items() if key in ('source_identity', 'page', 'start_line', 'end_line')} for item in windows], 'supplied_windows': windows, 'required_images': [{key: value for key, value in item.items() if key not in ('input_start_byte', 'input_end_byte')} for item in images], 'supplied_images': images}
    write(R / 'availability-manifest.json', evidence_manifest)
    write(R / 'offline-preflight.json', check_manifest(R / 'availability-manifest.json', availability))
    protected = {}
    for tree in (ORIGINAL, code):
        for path in tree.rglob('*'):
            if path.is_file() and (tree == code or path.suffix == '.pdf' or path.name in ('canonical.sqlite3', 'working.sqlite3')):
                protected[str(path)] = sha(path)
    for path in work.rglob('*'):
        if path.is_file() and (path.suffix == '.pdf' or path.name in ('canonical.sqlite3', 'working.sqlite3')):
            protected[str(path)] = sha(path)
            path.chmod(0o444)
    with sqlite3.connect(f'file:{work}/.rob2-kit/canonical.sqlite3?mode=ro', uri=True) as connection:
        try:
            connection.execute('CREATE TABLE forbidden_probe(x)')
        except sqlite3.OperationalError as error:
            assert 'readonly' in str(error)
        else:
            raise AssertionError('Canonical write unexpectedly allowed')
    write(D / 'protected.json', protected)
    before_sessions = {str(path): sha(path) for path in (HOME / 'sessions').rglob('*.jsonl')}
    manifest = {'code_sha': '22e84f3fca0aba63639e35684446e7aa91098ca0', 'workspace': str(work), 'original_workspace': str(ORIGINAL), 'code': str(code), 'home': str(HOME), 'model': 'gpt-6-luna', 'effort': 'medium', 'allowed_tools': declared['allowed_tools'], 'source_check_snapshot': declared['snapshot_identity'], 'prompt_sha256': sha(D / 'request/prompt.txt'), 'request_sha256': sha(D / 'request/request.json'), 'command_sha256': sha(D / 'command.json'), 'criteria_sha256': sha(R / 'private-criteria.md'), 'runner_sha256': sha(R / 'run_once.py'), 'availability_manifest_sha256': sha(R / 'availability-manifest.json'), 'availability_path': str(availability), 'availability_not_model_input': True, 'home_config_sha256': sha(HOME / 'config.toml'), 'existing_rollouts': before_sessions, 'protected_manifest_sha256': sha(D / 'protected.json'), 'no_retry': True, 'limits': {'invocations': 1, 'tool_input_cutoff': False, 'output_alert': 6000, 'wall_alert': 480, 'idle_alert': 90}, 'original_revision': state['revision'], 'sources_match_Code_benchmark': True, 'credentials_read_or_copied': False}
    write(R / 'manifest.json', manifest)
    write(R / 'preparation.json', {'claims': len(json.loads((D / 'request/packet.json').read_text())['claims']), 'cited_spans': len(json.loads((D / 'request/packet.json').read_text())['cited_spans']), 'initial_images': len(declared['images']), 'full_source_pages': len(windows), 'prompt_bytes': (D / 'request/prompt.txt').stat().st_size, 'model_calls': 0, 'canonical_readonly': True})
    print((R / 'preparation.json').read_text())


if __name__ == '__main__':
    main()
