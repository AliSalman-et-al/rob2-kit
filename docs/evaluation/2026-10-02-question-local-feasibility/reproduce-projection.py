"""Replay captured construction errors one question at a time, without inference."""
import json
from pathlib import Path

from pydantic import ValidationError

from rob2_kit.workflow_models import DomainSaveAnswer

root = Path(__file__).resolve().parents[1]
calls = json.loads((root / '2026-10-02-frozen-an-5a3e580/an-2021/submissions.json').read_text())
for call in calls:
    print('event', call['event_ordinal'])
    for answer in call['arguments']['answers']:
        try:
            DomainSaveAnswer.model_validate(answer)
            errors = []
        except ValidationError as error:
            errors = [(entry['loc'], entry['type']) for entry in error.errors()]
        print(answer['question_id'], errors)
