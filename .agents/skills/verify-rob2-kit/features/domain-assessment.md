# Domain assessment

After approval, the host fetches each domain's context: the official
signalling questions, guidance and prior answers. It then saves answers with
cited evidence. The server applies the official RoB 2 algorithm, and the host
may adjudicate a different judgment with a written rationale.

## Sub-features

- `context` is the paginated `get_domain_context`, whose `context_page.next_cursor` drains the remaining pages.
- `save` is `save_domain_judgment`, which returns a checkpoint with the algorithm's judgment.
- `active-questions` rejects answers to inactive questions with `answers_must_match_active_questions`.
- `stale` rejects a stale `expected_revision`.
- `adjudication` resaves the same answers with `supersedes` (the checkpoint identity) and `adjudication: {judgment, rationale, evidence}`.
- `resume` lets a new host session (a new `Agent`) on the same workspace continue from `get_status`.
- `working-notes` saves a working checkpoint with `save_working_checkpoint`.

## How to get to it (user POV)

- The host follows `next_action`, which becomes `get_domain_context` for the next unsaved domain after approval.

## Driving it with the e2e Agent

Preconditions: the proposal is approved and `agent.read_required()` has run.

- **Low-risk pass.** For each domain in `low_risk_answers(agent)`, call `agent.context()`, then `agent.save_domain(domain_id, answers)`. Each `data.checkpoint.judgment == "low"`.
- **High-risk path.** Use `trial.build_open_label` and the answers in `tests/e2e/test_high_risk.py`. The measurement and deviations domains come out `high`, and the overall judgment is `high`.
- **Adjudicate.** Call `agent.save_domain(d, same_answers, supersedes=<checkpoint identity>, adjudication={"judgment": "high", "rationale": "...", "evidence": [handle]})`. The adopted judgment changes while the proposed algorithm judgment is kept.
- **Resume.** Close the agent, open `Agent(ws)` again, and call `agent.next_action()`. It points to the next unsaved domain.

## Gotchas

- Answers decide which later questions are active. Fetch the context again after changing an earlier answer.
- Adjudication evidence must already be cited by those answers. Otherwise the repair is `adjudication_evidence_not_in_checkpoint`.
- Counterevidence entries must point at the answer's own bases.
