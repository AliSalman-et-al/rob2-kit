"""Freeze one authorized corrected-schema recovery, preserving the failed attempt."""
from __future__ import annotations

import hashlib
import io
import json
import shutil
import subprocess
import tarfile
from pathlib import Path

import jsonschema

from scripts.diagnostic_evidence_preflight import check_manifest
from scripts.export_factual_audit import check_native_review_schema, native_review_schema

R = Path(__file__).resolve().parent
REPO = R.parents[2]
OLD_R = R.parent / '2026-10-04-freeman-source-check'
OLD_D = REPO.parent / 'diagnostics/freeman-source-check-20261004'
D = REPO.parent / 'diagnostics/freeman-source-check-recovery-20261004'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main():
    assert not D.exists() and not (R / 'manifest.json').exists(), 'Never overwrite a recovery run'
    base = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip()
    assert base == '6308a67' or base.startswith('6308a67')
    old = json.loads((OLD_R / 'manifest.json').read_text())
    for name, digest in json.loads((OLD_D / 'answer-freeze.json').read_text()).items():
        assert sha(Path(name)) == digest
    D.mkdir(parents=True)
    shutil.copytree(OLD_D / 'workspace', D / 'workspace')
    shutil.copytree(OLD_D / 'request', D / 'request')
    code = D / 'code'
    code.mkdir()
    archive = subprocess.check_output(['git', 'archive', base], cwd=REPO)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(code, filter='data')
    schema = native_review_schema()
    jsonschema.Draft202012Validator.check_schema(schema)
    check_native_review_schema(schema)
    write(D / 'request/response-schema.json', schema)
    command = json.loads((OLD_D / 'command.json').read_text())
    command = [value.replace(str(OLD_D), str(D)) for value in command]
    write(D / 'command.json', command)
    # Science/task/pixels are byte-identical. Only native schema and runtime paths change.
    for name in ('packet.json', 'prompt.txt', 'instructions.md'):
        assert sha(D / 'request' / name) == sha(OLD_D / 'request' / name)
        shutil.copyfile(D / 'request' / name, R / name)
    for path in (D / 'request').glob('*.png'):
        assert sha(path) == sha(OLD_D / 'request' / path.name)
    declared = json.loads((D / 'request/request.json').read_text())
    declared['command'] = command
    for image in declared['images']:
        image['path'] = image['path'].replace(str(OLD_D), str(D))
    declared['files_sha256'] = {path.name: sha(path) for path in (D / 'request').iterdir() if path.is_file() and path.name != 'request.json'}
    declared['attempt'] = 'one authorized technical recovery from HTTP400, not accuracy retry'
    write(D / 'request/request.json', declared)
    for name in ('response-schema.json', 'request.json'):
        shutil.copyfile(D / 'request' / name, R / name)
    write(R / 'command.json', command)
    for name in ('availability-manifest.json', 'source-provenance.json', 'private-criteria.md'):
        shutil.copyfile(OLD_R / name, R / name)
    shutil.copyfile(OLD_D / 'availability.bin', D / 'availability.bin')
    write(R / 'offline-preflight.json', check_manifest(R / 'availability-manifest.json', D / 'availability.bin'))
    home = Path(old['home'])
    protected = {}
    for tree in (Path(old['original_workspace']), OLD_D, code):
        for path in tree.rglob('*'):
            if path.is_file():
                protected[str(path)] = sha(path)
    for path in (D / 'workspace').rglob('*'):
        if path.is_file() and (path.suffix == '.pdf' or path.name in ('canonical.sqlite3', 'working.sqlite3')):
            protected[str(path)] = sha(path)
            path.chmod(0o444)
    write(D / 'protected.json', protected)
    m = {**old, 'code_sha': base, 'workspace': str(D / 'workspace'), 'code': str(code), 'original_failed_attempt': str(OLD_D), 'prompt_sha256': sha(D / 'request/prompt.txt'), 'request_sha256': sha(D / 'request/request.json'), 'command_sha256': sha(D / 'command.json'), 'criteria_sha256': sha(R / 'private-criteria.md'), 'runner_sha256': sha(R / 'run_once.py'), 'availability_manifest_sha256': sha(R / 'availability-manifest.json'), 'availability_path': str(D / 'availability.bin'), 'existing_rollouts': {str(path): sha(path) for path in (home / 'sessions').rglob('*.jsonl')}, 'protected_manifest_sha256': sha(D / 'protected.json'), 'technical_recovery': True, 'no_further_paid_attempt_after_this': True, 'schema_sha256': sha(D / 'request/response-schema.json')}
    write(R / 'manifest.json', m)
    write(R / 'schema-preflight.json', {'standard_schema': 'Draft202012 check_schema passed', 'native_profile': 'root object/no root anyOf; all object properties required; additionalProperties false; local $defs references resolve; conservative supported keywords; constraints preserved locally', 'installed_openai_sdk': False, 'installed_jsonschema': True, 'official_source': 'https://developers.openai.com/api/docs/guides/structured-outputs', 'schema_sha256': m['schema_sha256'], 'original_schema_sha256': sha(OLD_R / 'response-schema.json'), 'first_offline_fix_sha256': sha(OLD_R / 'postfreeze-native-schema.json'), 'fixes': ['nullable fields required', 'prefixItems to fixed homogeneous items', 'Pydantic ge to minimum', 'defaults/string length keywords removed from native wire, local validation unchanged'], 'deterministic_preflight_tests': '7 passed', 'provider_acceptance_not_yet_observed': True, 'factual_prompt_packet_image_bytes_identical': True, 'model': 'gpt-6-luna', 'effort': 'medium', 'prior_failed_attempt_preserved': True})
    print(json.dumps({'code_sha': base, 'schema_sha256': m['schema_sha256'], 'prompt_sha256': m['prompt_sha256'], 'packet_unchanged': True, 'fullsource_preflight_passed': True, 'model_calls': 0}))


if __name__ == '__main__':
    main()
