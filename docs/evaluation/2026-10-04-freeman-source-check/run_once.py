"""One authorized fresh native source-check invocation; no retry or author continuation."""
from __future__ import annotations

import hashlib
import json
import os
import selectors
import signal
import subprocess
import time
from pathlib import Path

from scripts.diagnostic_evidence_preflight import launch_checked

R = Path(__file__).resolve().parent
D = R.parents[2].parent / 'diagnostics/freeman-source-check-20261004'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def main():
    manifest = json.loads((R / 'manifest.json').read_text())
    home = Path(manifest['home'])
    work = Path(manifest['workspace'])
    assert not (D / 'run.json').exists(), 'Exactly one invocation; preserve previous run'
    for path, digest in [(R / 'run_once.py', manifest['runner_sha256']), (R / 'private-criteria.md', manifest['criteria_sha256']), (D / 'request/prompt.txt', manifest['prompt_sha256']), (D / 'command.json', manifest['command_sha256']), (D / 'request/request.json', manifest['request_sha256']), (D / 'protected.json', manifest['protected_manifest_sha256']), (home / 'config.toml', manifest['home_config_sha256'])]:
        assert sha(path) == digest, path
    protected = json.loads((D / 'protected.json').read_text())

    def preservation():
        for name, digest in {**protected, **manifest['existing_rollouts']}.items():
            assert sha(Path(name)) == digest, ('Frozen file changed', name)

    preservation()
    command = json.loads((D / 'command.json').read_text())
    records = {}
    contexts = []
    calls = {}
    finals = set()
    alerts = []
    stop = None
    buffer = b''
    started = last = time.monotonic()

    def telemetry():
        nonlocal stop
        new = [path for path in (home / 'sessions').rglob('*.jsonl') if str(path) not in manifest['existing_rollouts']]
        if len(new) > 1:
            stop = stop or 'multiple new sessions'
        for path in new:
            for line in path.read_text().splitlines():
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                payload = row.get('payload', {})
                if row.get('type') == 'token_usage_record':
                    records[payload['response_id']] = {'timestamp': row.get('timestamp'), **payload}
                elif row.get('type') == 'turn_context':
                    value = {'model': payload.get('model'), 'effort': payload.get('effort')}
                    if value not in contexts:
                        contexts.append(value)
                    if value != {'model': 'gpt-6-luna', 'effort': 'medium'}:
                        stop = stop or 'model/settings mismatch'
        return new

    def usage():
        return {key: sum(row['usage'].get(key, 0) for row in records.values()) for key in ('input_tokens', 'cached_input_tokens', 'output_tokens', 'reasoning_output_tokens')}

    def consume(chunk):
        nonlocal buffer, last, stop
        log.write(chunk)
        log.flush()
        buffer += chunk
        while b'\n' in buffer:
            line, buffer = buffer.split(b'\n', 1)
            if not line.strip():
                continue
            row = json.loads(line)
            item = row.get('item', {})
            kind = item.get('type')
            if kind == 'mcp_tool_call' or (kind in ('agent_message', 'reasoning') and any(item.get(key) for key in ('text', 'summary', 'content'))):
                last = time.monotonic()
            if kind == 'mcp_tool_call':
                calls[item['id']] = {'server': item.get('server'), 'tool': item.get('tool'), 'completed': row.get('type') == 'item.completed'}
                if item.get('server') != 'rob2' or item.get('tool') not in manifest['allowed_tools']:
                    stop = stop or 'tool outside source-only allowlist'
                trial = item.get('arguments', {}).get('trial_id')
                if trial not in (None, 'freeman-2020'):
                    stop = stop or 'outside selected Trial'
            elif kind in ('command_execution', 'web_search', 'image_view', 'collab_tool_call'):
                stop = stop or 'forbidden tool'
            if row.get('type') == 'item.completed' and kind == 'agent_message':
                finals.add(item['id'])

    def check():
        nonlocal stop
        telemetry()
        preservation()
        now = time.monotonic()
        if (D / 'stop-request.json').exists():
            stop = stop or json.loads((D / 'stop-request.json').read_text())['reason']
        levels = [('output review', usage()['output_tokens'] >= 6000), ('wall review', now - started >= 480), ('idle review', now - last >= 90)]
        for reason, reached in levels:
            if reached and not any(alert['reason'] == reason for alert in alerts):
                alert = {'reason': reason, 'elapsed_seconds': now - started, 'idle_seconds': now - last, 'tool_calls': len(calls), 'usage': usage()}
                alerts.append(alert)
                write(D / 'alerts.json', alerts)
                print(json.dumps({'supervision_alert': alert}), flush=True)
        write(D / 'live-progress.json', {'elapsed_seconds': now - started, 'idle_seconds': now - last, 'tool_calls': len(calls), 'usage': usage(), 'latest_tools': list(calls.values())[-3:], 'alerts': alerts})
        return stop

    write(D / 'run.json', {'state': 'started', 'no_retry': True, 'command': command})
    with (D / 'events.jsonl').open('wb') as log, (D / 'stderr.log').open('wb') as error:
        process = launch_checked(command, manifest_path=R / 'availability-manifest.json', input_path=Path(manifest['availability_path']), receipt_path=R / 'launch-preflight.json', expected_manifest_sha256=manifest['availability_manifest_sha256'], cwd=work, env={**os.environ, 'CODEX_HOME': str(home)}, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=error, start_new_session=True)
        process.stdin.write((D / 'request/prompt.txt').read_bytes())
        process.stdin.close()
        os.set_blocking(process.stdout.fileno(), False)
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        try:
            while process.poll() is None:
                for key, _ in selector.select(.25):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if chunk:
                        consume(chunk)
                if check():
                    break
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
            while True:
                try:
                    chunk = os.read(process.stdout.fileno(), 65536)
                except BlockingIOError:
                    break
                if not chunk:
                    break
                consume(chunk)
            selector.close()
    sessions = telemetry()
    preservation()
    u = usage()
    write(D / 'durable-token-usage-records.json', list(records.values()))
    write(D / 'effective-model.json', contexts)
    write(D / 'run.json', {'exit_code': process.returncode, 'stop': stop, 'elapsed_seconds': time.monotonic() - started, 'tool_calls': len(calls), 'calls': calls, 'final_messages': len(finals), 'provider_responses': len(records), 'usage': u, 'uncached_input_tokens': u['input_tokens'] - u['cached_input_tokens'], 'effective_model': contexts, 'native_sessions': [str(path) for path in sessions], 'alerts': alerts, 'no_retry': True, 'protected_hashes_unchanged': True})
    write(D / 'answer-freeze.json', {str(path): sha(path) for path in [D / 'request/response.json', D / 'events.jsonl', D / 'run.json', D / 'durable-token-usage-records.json', *sessions] if path.exists()})
    print((D / 'run.json').read_text())
    print('Response frozen before adjudication; no assessor feedback.')


if __name__ == '__main__':
    main()
