"""Offline audit only, after the model output freeze; never repairs assessments."""
from pathlib import Path
import hashlib
import json
import shutil
import zipfile

R = Path(__file__).resolve().parent
M = json.loads((R / 'run-manifest.json').read_text())
D = Path(M['staging'])

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def write(name, value):
    (R / name).write_text(json.dumps(value, indent=2) + '\n')

freeze = json.loads((R / 'output-freeze.json').read_text())
assert all(sha(R / name) == digest for name, digest in freeze.items())
original = json.loads((R / 'original-preservation.json').read_text())
assert all(sha(Path(name)) == digest for name, digest in original.items())
bundle = next((D / 'workspace/.rob2-kit/finalized').glob('*.zip'))
with zipfile.ZipFile(bundle) as archive:
    canonical = json.loads(archive.read('canonical.json'))
    evidence = {
        e['identity']: e
        for name in archive.namelist() if name.startswith('evidence/')
        for e in [json.loads(archive.read(name))]
    }
preflight = json.loads((R / 'preflight.json').read_text())
assert all(canonical['domain_records'][key]['identity'] == identity
           for key, identity in preflight['saved_domains'].items())
assert canonical['proposal_acknowledgment']['identity'] == preflight['approval_identity']
result = canonical['proposal']['payload']['results'][0]
assert result['relation'] == 'narrower'
assert result['target']['effect_of_interest'] == 'assignment'
measurement = canonical['domain_records']['gupta-2024:domain:measurement']
answer = next(a for a in measurement['answers'] if a['question_id'] == 'sq:measurement:differential')
selected = [evidence[b['evidence']] for b in answer['bases']]
assert all('13/86' not in e['quote'] and '13/94' not in e['quote'] for e in selected)
correct = next(e for e in evidence.values() if e['page'] == 7 and 'ec3fc' in e['source_id'])
assert '13/86' in correct['quote'] and '13/94' in correct['quote']
usage = json.loads((R / 'experiment.json').read_text())['usage']
old = {'input_tokens': 8358147, 'cached_input_tokens': 8077568,
       'output_tokens': 16523, 'reasoning_output_tokens': 4927}
write('usage-accounting.json', {
    'original': old, 'new_fork_only': usage,
    'combined': {key: old[key] + usage[key] for key in old},
    'method': 'New durable provider response IDs exclude every inherited baseline ID; sum each new response ID once. Reasoning output is a subset of output, not additive.',
    'original_tools': 56, 'new_tools': 13, 'combined_tools': 69,
    'original_turns': 2, 'new_turns': 1, 'combined_turns': 3,
    'original_wall_seconds': 535.508,
    'new_wall_seconds': json.loads((R / 'experiment.json').read_text())['elapsed_seconds'],
    'preflight_model_calls': 0,
})
write('audit.json', {
    'output_freeze_verified': True, 'original_protected_hashes_unchanged': True,
    'original_saved_domain_identities_unchanged': preflight['saved_domains'],
    'approval_identity_unchanged': preflight['approval_identity'],
    'target_relation_preserved': result['relation'],
    'finalized_revision': 12,
    'bundle': {'name': bundle.name, 'sha256': sha(bundle), 'bytes': bundle.stat().st_size},
    'measurement_count_citation': {
        'outcome': 'Known citation defect persists after native optional review',
        'selected': [{k: e[k] for k in ['handle', 'source_id', 'page', 'start_line', 'end_line']} for e in selected],
        'actual_support': {k: correct[k] for k in ['handle', 'source_id', 'page', 'start_line', 'end_line']},
        'distinction': 'Counts correct in main report; similar non-testing proportions are an inference. Existing selected sources do not establish the numerical clause. This is not proof that D4 Low is wrong.'},
    'image_delivery': {'new_render_calls': 0, 'outcome': 'Not tested in this continuation; original visual uncertainty retained, not repaired.'},
    'plan_vs_result': {'outcome': 'D5 separates SAP adjusted primary inference and actual Table 2 adjusted RR; actual restricted estimates read in appendix Table S9. SAP document history says Not yet unblinded, rather than a mere requirement.'},
    'review_changes': {'new_domain_records': ['domain:selection'], 'revisions_to_original_domains': 0,
                       'outcome': 'Model chose no ordinary revisions despite receiving measurement findings and cited text.'},
    'verifiers': {'producer': 'passed', 'independent': 'passed',
                  'limitation': 'Structural integrity is not scientific entailment verification.'},
})
shutil.copyfile(bundle, R / bundle.name)
write('artifact-hashes.json', {p.name: sha(p) for p in sorted(R.iterdir())
                             if p.is_file() and p.name != 'artifact-hashes.json'})
print('Frozen outputs and original files verified; known D4 citation defect persists.')
