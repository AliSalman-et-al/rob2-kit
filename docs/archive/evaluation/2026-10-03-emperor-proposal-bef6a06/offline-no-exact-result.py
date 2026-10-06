"""Replay existing shape controls; no inference, source assertion or state mutation."""
from pathlib import Path
import copy
import json
import re
from pydantic import ValidationError
from rob2_kit.workflow_models import ResultProposal, MissingResultProposal, ProposalDraft
from rob2_kit.application.proposal import _proposal_shape_repairs, _valid_no_supported_sources_basis

reference = Path('src/rob2_kit/skills/rob2-assess/references/result.md').read_text()
example = json.loads(re.findall(r'```json\n(.*?)\n```', reference, flags=re.S)[0])['results'][0]
exact = copy.deepcopy(example)
exact['relation'] = 'exact'
r = ResultProposal.model_validate(exact).to_draft()
repairs = _proposal_shape_repairs(ProposalDraft(results=(r,), expected_revision=0), {r.trial_id: 'Course quiz score'})
assert len([item for item in repairs if item['code'] == 'exact_result_scope_not_established']) == 8
near = copy.deepcopy(example)
near['relation'] = 'related'
near['relation_rationale'] = 'Complete nearby source Result; equivalence unresolved.'
near['clarity'] = {
    'outcome_definition': 'specified', 'measurement': 'specified', 'time_point': 'unclear',
    'analysis_population': 'conflicting', 'comparison_groups': 'specified',
    'effect_measure': 'specified', 'source_table_meaning': 'specified',
    'eligible_result_choice': 'unclear',
}
r = ResultProposal.model_validate(near).to_draft()
assert not _proposal_shape_repairs(ProposalDraft(results=(r,), expected_revision=0), {r.trial_id: 'Course quiz score'})
assert r.target.time_point_or_window.description == ResultProposal.model_validate(example).to_draft().target.time_point_or_window.description
missing = MissingResultProposal.model_validate({
    'trial_id': 'fictional_quiz_trial', 'relation': 'ambiguous', 'missing_facts': [{
        'fact': 'Complete comparative Result for the requested scope',
        'basis': {'kind': 'missing_reporting', 'evidence': 'eh_0000000000000001'},
    }],
})
assert missing.to_draft().kind == 'unavailable'
try:
    MissingResultProposal.model_validate({'trial_id': 'fictional_quiz_trial', 'relation': 'unavailable', 'missing_facts': []})
except ValidationError:
    pass
else:
    raise AssertionError('Empty missing facts accepted')
assert not _valid_no_supported_sources_basis({
    'trials': [{'id': 'fictional_quiz_trial', 'sources': [{'id': 'source'}]}],
    'conditions': [],
}, 'fictional_quiz_trial')
print('Five existing shape controls passed; this does not establish source entailment.')
