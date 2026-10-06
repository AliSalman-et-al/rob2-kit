"""Qualified recovery; validation completes before any process can be spawned."""
import hashlib
import json
import os
from pathlib import Path
import sys
import time

from rob2_kit.application._state import _state
from scripts.diagnostic_evidence_preflight import launch_checked

D = Path('/home/ali/Documents/Codex/2026-10-02/task-4/diagnostics/avatar-d4-guidance-pair')
SESSIONS = {'old': '01a10987-27d9-7002-bbcf-a1be340ee305',
            'new': '01a10987-6335-7141-a130-ccde2485a3b2'}
sha = lambda b: hashlib.sha256(b).hexdigest()


def validate(arm, session, receipt, state, candidate):
    if arm not in SESSIONS or session != SESSIONS[arm]:
        raise ValueError('exact original session required; fresh or empty session forbidden')
    ack = receipt.get('acknowledgment_record')
    if (receipt.get('approved') is not True or not isinstance(ack, dict)
        or receipt.get('outcome') != 'success'
        or receipt.get('state_revision') != state.get('revision')
        or state.get('phase') != 'assessment'
        or state.get('proposal_review') != candidate
        or ack.get('review_identity') != candidate['identity']
        or ack != state.get('proposal_acknowledgment')
        or ack not in state.get('acknowledgments', [])
        or receipt.get('acknowledgment') != ack.get('identity')
        or state.get('proposal', {}).get('payload') != candidate['candidate']['proposal']):
        raise ValueError('approval must match exact current workspace/revision/Result')


def plan(arm, session):
    a = D / arm
    rows = [json.loads(line) for line in (a/'turn-1.jsonl').read_text().splitlines() if line]
    if session != next(r['thread_id'] for r in rows if r['type']=='thread.started'):
        raise ValueError('original thread receipt mismatch')
    receipt = json.loads((a/'recovery-approval-receipt.json').read_text())
    state = _state(a/'workspace')
    candidate = json.loads((a/'scope-review-candidate.json').read_text())
    validate(arm, session, receipt, state, candidate)
    for name, digest in json.loads((D/'prelaunch-freeze.json').read_text()).items():
        if name.startswith(('old/workspace/', 'new/workspace/')):
            continue
        if sha((D/name).read_bytes()) != digest:
            raise ValueError('frozen input changed: '+name)
    for name, digest in json.loads((D/'terminal-failure-freeze.json').read_text()).items():
        if sha((D/name).read_bytes()) != digest:
            raise ValueError('failed attempt artifact changed: '+name)
    if not (D/'amended-recovery-protocol.json').is_file():
        raise ValueError('amended protocol required')
    if any((a/name).exists() for name in ('recovery-3.jsonl','recovery-3.stderr','recovery-3-final.txt','recovery-3-launch.json')):
        raise ValueError('unique recovery logs already exist; never overwrite')
    command = ['/home/ali/.nvm/versions/node/v24.21.0/bin/codex','exec','resume',
               '--json','--skip-git-repo-check','-m','gpt-6-luna','-c',
               'model_reasoning_effort="medium"','-o',str(a/'recovery-3-final.txt'),session,'-']
    return a, command


def main():
    arm,session = sys.argv[1:3]
    a,cmd = plan(arm,session)
    if sys.argv[3:] != ['--execute']:
        print(json.dumps({'offline_validated_command':cmd}));return
    inp=a/'recovery-3-input.txt'
    inp.write_text('Continue this original assessment session after normal ProposalReview approval. Use get_status and normal guidance to complete the previously requested Domain only.\n')
    manifest=json.loads((a/'evidence-manifest.json').read_text());manifest['input_sha256']=sha(inp.read_bytes())
    m=a/'recovery-3-manifest.json';m.write_text(json.dumps(manifest,indent=2)+'\n')
    launch={'command':cmd,'started_at':time.time(),'protocol':'qualified recovery after TWO accidental extra get_status-only threads; retain overhead','approval_receipt_sha256':sha((a/'recovery-approval-receipt.json').read_bytes()),'config_sha256':sha((a/'home/config.toml').read_bytes())}
    (a/'recovery-3-launch.json').write_text(json.dumps(launch,indent=2)+'\n')
    env={**os.environ,'CODEX_HOME':str(a/'home')}
    p=launch_checked(cmd,manifest_path=m,input_path=inp,evidence_bundle_path=D/'native-evidence.bundle',receipt_path=a/'recovery-3-preflight.json',expected_manifest_sha256=sha(m.read_bytes()),stdin=open(inp,'rb'),stdout=open(a/'recovery-3.jsonl','wb'),stderr=open(a/'recovery-3.stderr','wb'),cwd=a/'workspace',env=env,start_new_session=True)
    (a/'recovery-3-process.json').write_text(json.dumps({'pid':p.pid,'started_at':time.time()})+'\n')
    print('RESUMED',arm,session,p.pid,flush=True)
    rc=p.wait();(a/'recovery-3-exit.json').write_text(json.dumps({'returncode':rc,'finished_at':time.time()})+'\n');print('EXIT',arm,rc,flush=True)


if __name__=='__main__':main()
