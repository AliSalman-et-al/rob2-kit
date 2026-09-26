from __future__ import annotations

import hashlib
import json
import runpy
import subprocess
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).parents[1] / "scripts"
_LAUNCHER = runpy.run_path(str(_SCRIPTS / "run_development_comparison.py"))


def _hash(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _campaign_inputs(
    tmp_path: Path, *, factor: str = "evidence_exposure"
) -> tuple[Path, Path, Path, Path, Path]:
    config = json.loads(
        (
            Path(__file__).parents[1] / "docs/evaluation/development-comparison-v0.3.example.json"
        ).read_text(encoding="utf-8")
    )
    intervention_ids = [arm["intervention_id"] for arm in config["arms"]]
    interventions = {key: f"sha256:{index:064x}" for index, key in enumerate(intervention_ids, 1)}
    prompt = b"Assess the declared Result using the supplied Sources.\n"
    config["plan"]["host"]["prompt_identity"] = _hash(prompt)

    input_root = tmp_path / "inputs"
    input_root.mkdir()
    prompt_path = input_root / "prompt.txt"
    prompt_path.write_bytes(prompt)
    run_inputs = []
    base_source = input_root / "main-article.txt"
    base_source.write_text("source bytes", encoding="utf-8")
    expected_result = {
        "trial": "ARASENS",
        "comparison": [
            {"id": "treatment", "assignment": "Treatment"},
            {"id": "control", "assignment": "Control"},
        ],
        "endpoint_definition": "Time from randomization to disease progression or death.",
        "population": "All randomized participants.",
        "window": "From randomization to progression, death, or last follow-up.",
        "reported_scope": {
            "form": "comparative_effect",
            "analysis_population": "All randomized participants.",
            "endpoint": {"name": "Progression-free survival"},
            "effect_measure": "Hazard ratio",
            "estimate": "0.50",
            "precision": "95% CI, 0.40 to 0.60",
        },
    }
    config["plan"]["cases"][0]["result_identity"] = _hash(
        json.dumps(expected_result, sort_keys=True, separators=(",", ":")).encode()
    )
    baseline_source_identity = _hash(
        json.dumps(
            [
                {
                    "name": base_source.name,
                    "role": "main_article",
                    "sha256": hashlib.sha256(base_source.read_bytes()).hexdigest(),
                }
            ],
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    )
    config["plan"]["cases"][0]["source_identity"] = baseline_source_identity
    decisive_source = input_root / "decisive-passages.txt"
    decisive_source.write_text("additional relevant passages", encoding="utf-8")
    selected_pair = next(pair for pair in config["pairs"] if pair["factor"] == factor)
    selected_arms = [
        next(arm for arm in config["arms"] if arm["id"] == selected_pair[key])
        for key in ("left", "right")
    ]
    treatment_source = decisive_source
    if factor == "fact_binding":
        treatment_source = input_root / "scope-matched-facts.json"
        treatment_source.write_text(
            json.dumps(
                {
                    "schema": "rob2-kit.scope-matched-facts.v1",
                    "trial_id": "ARASENS",
                    "outcome_id": "Progression-Free Survival",
                    "result_identity": config["plan"]["cases"][0]["result_identity"],
                    "facts": [
                        {
                            "domain_id": "domain:missing",
                            "question_id": "missing-data-status",
                            "statement": "The article reports the randomized population.",
                            "source_name": base_source.name,
                            "locator": "Results, paragraph 2",
                        }
                    ],
                    "counterevidence": [],
                    "unknowns": [],
                }
            ),
            encoding="utf-8",
        )
    for index, arm in enumerate(selected_arms):
        intervention_id = arm["intervention_id"]
        sources = [{"path": base_source.name, "name": base_source.name, "role": "main_article"}]
        if index == 1:
            sources.append(
                {
                    "path": treatment_source.name,
                    "name": (
                        "scope-matched-facts.json"
                        if factor == "fact_binding"
                        else treatment_source.name
                    ),
                    "role": "other",
                }
            )
        case_path = input_root / f"case-{index}.json"
        case_path.write_text(
            json.dumps(
                {
                    "schema": "rob2-kit.rsi-case.v1",
                    "trial": "ARASENS",
                    "requested_outcome": "Progression-Free Survival",
                    "approved_scope": "Frozen primary PFS Result scope.",
                    "campaign_id": "development-test",
                    "expected_result": expected_result,
                    "sources": sources,
                }
            ),
            encoding="utf-8",
        )
        run_inputs.append(
            {
                "intervention_id": intervention_id,
                "case_id": "ARASENS-pfs-D3",
                "case_file": case_path.name,
                "prompt_file": prompt_path.name,
            }
        )

    config_path = tmp_path / "config.json"
    interventions_path = tmp_path / "interventions.json"
    inputs_path = input_root / "inputs.json"
    runner_path = tmp_path / "fake_runner.py"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    interventions_path.write_text(json.dumps(interventions), encoding="utf-8")
    inputs_path.write_text(
        json.dumps({"schema": "rob2-kit.development-comparison-inputs.v1", "runs": run_inputs}),
        encoding="utf-8",
    )
    runner_path.write_text(
        """import hashlib
import json
import runpy
import sys
from pathlib import Path
args = sys.argv[1:]
run_dir = Path(args[args.index('--run-dir') + 1])
phase = int(args[args.index('--phase') + 1])
prompt_path = Path(args[args.index('--prompt') + 1])
prompt_digest = hashlib.sha256(prompt_path.read_bytes()).hexdigest()
workspace = run_dir / 'workspace'
if phase == 1:
    case_path = Path(args[args.index('--case') + 1])
    case_digest = hashlib.sha256(case_path.read_bytes()).hexdigest()
    case = json.loads(case_path.read_text())
    sys.path.insert(0, str(Path.cwd() / 'scripts'))
    prepare_workspace = runpy.run_path(
        str(Path.cwd() / 'scripts' / 'prepare_rsi_workspace.py')
    )['prepare_workspace']
    run_inputs = prepare_workspace(case_path, workspace)
    (run_dir / 'run-inputs.json').write_text(json.dumps(run_inputs))
    execution = {
        'state': 'waiting_for_user',
        'codex_session_id': 'codex-session-fixed',
        'attempt_id': 'runner-attempt-1',
        'manifest_sha256': case_digest,
        'prompt_sha256_by_phase': {'1': prompt_digest},
        'phases': [{'phase': 1, 'attempt_id': 'runner-attempt-1',
                    'codex_session_id': 'codex-session-fixed',
                    'prompt_sha256': prompt_digest}],
        'attempts': [{'attempt_id': 'runner-attempt-1', 'phase': 1,
                      'state': 'waiting_for_user'}],
    }
else:
    assert args[args.index('--session') + 1] == 'codex-session-fixed'
    assert Path(args[args.index('--prompt') + 1]).read_bytes() == b'Continue.\\n'
    assert (workspace / 'researcher-approved').is_file()
    execution_path = run_dir / 'execution.json'
    execution = json.loads(execution_path.read_text())
    execution['state'] = 'succeeded'
    execution['prompt_sha256_by_phase'][str(phase)] = prompt_digest
    execution['phases'].append({'phase': phase, 'attempt_id': 'runner-attempt-1',
                                'codex_session_id': 'codex-session-fixed',
                                'prompt_sha256': prompt_digest})
    execution['attempts'][-1]['state'] = 'succeeded'
run_dir.mkdir(parents=True, exist_ok=True)
(run_dir / f'phase-{phase}.jsonl').write_text('{\\\"event\\\":\\\"fake\\\"}\\n')
(run_dir / 'execution.json').write_text(json.dumps(execution))
print('fake runner completed')
""",
        encoding="utf-8",
    )
    return config_path, interventions_path, inputs_path, runner_path, input_root


def test_campaign_launches_each_frozen_arm_case_draw_isolated_and_retains_jsonl(
    tmp_path: Path,
) -> None:
    config, interventions, inputs, runner, _input_root = _campaign_inputs(tmp_path)
    campaign_dir = tmp_path / "campaign"

    result = _LAUNCHER["main"](
        [
            "--config",
            str(config),
            "--interventions",
            str(interventions),
            "--inputs",
            str(inputs),
            "--campaign-dir",
            str(campaign_dir),
            "--factor",
            "evidence_exposure",
            "--runner",
            str(runner),
        ]
    )

    assert result == 0
    launch = json.loads((campaign_dir / "launch.json").read_text(encoding="utf-8"))
    assert launch["status"] == "launches_finished"
    assert launch["declared_draw_count"] == 10
    assert launch["planned_draw_count"] == 4
    assert launch["selected_factor"] == "evidence_exposure"
    assert set(launch["excluded_pairs"]) == {"fact-binding", "context", "review"}
    assert len(launch["attempts"]) == 4
    assert {row["launch_status"] for row in launch["attempts"]} == {"phase_started"}
    assert len({row["run_dir"] for row in launch["attempts"]}) == 4
    assert {row["draw_id"] for row in launch["attempts"]} == {"draw-1", "draw-2"}
    assert {row["arm_id"] for row in launch["attempts"]} == {"baseline", "passages"}
    assert all(row["source_identities"] for row in launch["attempts"])
    assert all(
        "--require-isolated-host" in row["command"]
        and row["command"][row["command"].index("--model") + 1] == "gpt-6-luna"
        and row["command"][row["command"].index("--effort") + 1] == "medium"
        for row in launch["attempts"]
    )
    assert all((campaign_dir / row["trace"]).is_file() for row in launch["attempts"])
    assert all(row["trace_retained"] for row in launch["attempts"])
    assert all(row["source_materialization"]["status"] == "verified" for row in launch["attempts"])
    assert all(
        (campaign_dir / "logs" / f"{row['attempt_id']}.stdout.txt").is_file()
        for row in launch["attempts"]
    )
    assert all("labels" not in row for row in launch["attempts"])


def test_campaign_preflights_all_prompt_hashes_before_creating_campaign(tmp_path: Path) -> None:
    config, interventions, inputs, runner, _input_root = _campaign_inputs(tmp_path)
    prompt = inputs.parent / "prompt.txt"
    prompt.write_text("changed after the plan was frozen", encoding="utf-8")
    campaign_dir = tmp_path / "campaign"

    with pytest.raises(SystemExit) as error:
        _LAUNCHER["main"](
            [
                "--config",
                str(config),
                "--interventions",
                str(interventions),
                "--inputs",
                str(inputs),
                "--campaign-dir",
                str(campaign_dir),
                "--factor",
                "evidence_exposure",
                "--runner",
                str(runner),
            ]
        )

    assert error.value.code == 2
    assert not campaign_dir.exists()


def test_launcher_rechecks_frozen_prompt_before_each_draw(tmp_path: Path) -> None:
    config, interventions, inputs, runner, input_root = _campaign_inputs(tmp_path)
    campaign_dir = tmp_path / "campaign"
    manifest = _LAUNCHER["prepare_campaign"](
        json.loads(config.read_text(encoding="utf-8")),
        json.loads(interventions.read_text(encoding="utf-8")),
        json.loads(inputs.read_text(encoding="utf-8")),
        inputs_root=input_root,
        campaign_dir=campaign_dir,
        runner=runner,
        factor="evidence_exposure",
    )
    prompt = inputs.parent / "prompt.txt"
    calls = 0

    def mutate_after_first_draw(command, **kwargs):
        nonlocal calls
        result = subprocess.run(command, **kwargs)
        calls += 1
        if calls == 1:
            prompt.write_text("changed between planned draws", encoding="utf-8")
        return result

    assert (
        _LAUNCHER["launch_campaign"](manifest, campaign_dir, runner_call=mutate_after_first_draw)
        == 1
    )
    saved = json.loads((campaign_dir / "launch.json").read_text(encoding="utf-8"))
    assert calls == 1
    assert saved["attempts"][0]["launch_status"] == "phase_started"
    assert all(row["launch_status"] == "frozen_input_changed" for row in saved["attempts"][1:])


@pytest.mark.parametrize(
    "mutation",
    [
        "execution['manifest_sha256'] = '0' * 64",
        "execution['prompt_sha256_by_phase']['1'] = '0' * 64",
    ],
)
def test_launcher_rejects_runner_execution_digest_mismatch(tmp_path: Path, mutation: str) -> None:
    config, interventions, inputs, runner, _input_root = _campaign_inputs(tmp_path)
    runner_text = runner.read_text(encoding="utf-8")
    runner.write_text(
        runner_text.replace(
            "(run_dir / 'execution.json').write_text(json.dumps(execution))",
            mutation + "\n(run_dir / 'execution.json').write_text(json.dumps(execution))",
        ),
        encoding="utf-8",
    )
    campaign_dir = tmp_path / "campaign"

    assert (
        _LAUNCHER["main"](
            [
                "--config",
                str(config),
                "--interventions",
                str(interventions),
                "--inputs",
                str(inputs),
                "--campaign-dir",
                str(campaign_dir),
                "--factor",
                "evidence_exposure",
                "--runner",
                str(runner),
            ]
        )
        == 1
    )
    launch = json.loads((campaign_dir / "launch.json").read_text(encoding="utf-8"))
    assert all(row["launch_status"] == "execution_input_mismatch" for row in launch["attempts"])


def test_campaign_rejects_unsupported_review_factor_before_launch(tmp_path: Path) -> None:
    config, interventions, inputs, runner, _input_root = _campaign_inputs(tmp_path)
    campaign_dir = tmp_path / "campaign"

    with pytest.raises(SystemExit) as error:
        _LAUNCHER["main"](
            [
                "--config",
                str(config),
                "--interventions",
                str(interventions),
                "--inputs",
                str(inputs),
                "--campaign-dir",
                str(campaign_dir),
                "--factor",
                "review",
                "--runner",
                str(runner),
            ]
        )

    assert error.value.code == 2
    assert not campaign_dir.exists()


def test_campaign_rejects_evidence_arm_without_additional_source_availability(
    tmp_path: Path,
) -> None:
    config, interventions, inputs, runner, input_root = _campaign_inputs(tmp_path)
    treatment_case = input_root / "case-1.json"
    case_data = json.loads(treatment_case.read_text(encoding="utf-8"))
    case_data["sources"].pop()
    treatment_case.write_text(json.dumps(case_data), encoding="utf-8")
    campaign_dir = tmp_path / "campaign"

    with pytest.raises(SystemExit) as error:
        _LAUNCHER["main"](
            [
                "--config",
                str(config),
                "--interventions",
                str(interventions),
                "--inputs",
                str(inputs),
                "--campaign-dir",
                str(campaign_dir),
                "--factor",
                "evidence_exposure",
                "--runner",
                str(runner),
                "--dry-run",
            ]
        )

    assert error.value.code == 2
    assert not campaign_dir.exists()


def test_campaign_preflights_every_allowlisted_source_before_launch(tmp_path: Path) -> None:
    config, interventions, inputs, runner, input_root = _campaign_inputs(tmp_path)
    treatment_case = input_root / "case-1.json"
    case_data = json.loads(treatment_case.read_text(encoding="utf-8"))
    case_data["sources"][-1]["path"] = "missing-decisive-passages.txt"
    treatment_case.write_text(json.dumps(case_data), encoding="utf-8")
    campaign_dir = tmp_path / "campaign"

    with pytest.raises(SystemExit) as error:
        _LAUNCHER["main"](
            [
                "--config",
                str(config),
                "--interventions",
                str(interventions),
                "--inputs",
                str(inputs),
                "--campaign-dir",
                str(campaign_dir),
                "--factor",
                "evidence_exposure",
                "--runner",
                str(runner),
                "--dry-run",
            ]
        )

    assert error.value.code == 2
    assert not campaign_dir.exists()


@pytest.mark.parametrize("identity", ["result_identity", "source_identity"])
def test_campaign_rejects_unbound_planned_result_or_sources(tmp_path: Path, identity: str) -> None:
    config, interventions, inputs, runner, _input_root = _campaign_inputs(tmp_path)
    config_data = json.loads(config.read_text(encoding="utf-8"))
    config_data["plan"]["cases"][0][identity] = _hash(b"different frozen identity")
    config.write_text(json.dumps(config_data), encoding="utf-8")
    campaign_dir = tmp_path / "campaign"

    with pytest.raises(SystemExit) as error:
        _LAUNCHER["main"](
            [
                "--config",
                str(config),
                "--interventions",
                str(interventions),
                "--inputs",
                str(inputs),
                "--campaign-dir",
                str(campaign_dir),
                "--factor",
                "evidence_exposure",
                "--runner",
                str(runner),
                "--dry-run",
            ]
        )

    assert error.value.code == 2
    assert not campaign_dir.exists()


def test_case_materializes_through_production_rsi_workspace_preparer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _config, _interventions, _inputs, _runner, input_root = _campaign_inputs(tmp_path)
    case_path = input_root / "case-0.json"
    monkeypatch.syspath_prepend(str(_SCRIPTS))
    prepare_workspace = runpy.run_path(str(_SCRIPTS / "prepare_rsi_workspace.py"))[
        "prepare_workspace"
    ]

    run_inputs = prepare_workspace(case_path, tmp_path / "real-run" / "workspace")

    case_data = json.loads(case_path.read_text(encoding="utf-8"))
    assert run_inputs["expected_result"] == case_data["expected_result"]
    assert run_inputs["trial"] == case_data["trial"]
    assert {source["name"] for source in run_inputs["sources"]} == {"main-article.txt"}
    assert (
        tmp_path / "real-run" / "workspace" / "input" / "ARASENS" / "main-article.txt"
    ).read_text(encoding="utf-8") == "source bytes"


def test_fact_table_stays_in_campaign_inputs_outside_trial_corpus(tmp_path: Path) -> None:
    inputs_root = tmp_path / "eval" / "runs" / "comparison" / "inputs"
    inputs_root.mkdir(parents=True)
    config, interventions, inputs, runner, original_root = _campaign_inputs(
        inputs_root, factor="fact_binding"
    )
    source_dir = tmp_path / "eval" / "reference" / "sources" / "ARASENS"
    source_dir.mkdir(parents=True)
    (source_dir / "main-article.txt").write_bytes((original_root / "main-article.txt").read_bytes())
    for case_index in (0, 1):
        case_path = original_root / f"case-{case_index}.json"
        case_data = json.loads(case_path.read_text(encoding="utf-8"))
        case_data["sources"][0]["path"] = "../../../../reference/sources/ARASENS/main-article.txt"
        case_path.write_text(json.dumps(case_data), encoding="utf-8")

    # The source identity depends on the frozen descriptor and bytes, not the
    # campaign-relative path used to reach the baseline corpus.
    campaign_dir = tmp_path / "campaign"
    result = _LAUNCHER["main"](
        [
            "--config",
            str(config),
            "--interventions",
            str(interventions),
            "--inputs",
            str(inputs),
            "--campaign-dir",
            str(campaign_dir),
            "--factor",
            "fact_binding",
            "--runner",
            str(runner),
        ]
    )

    assert result == 0
    launch = json.loads((campaign_dir / "launch.json").read_text(encoding="utf-8"))
    facts_attempt = next(row for row in launch["attempts"] if row["arm_id"] == "facts")
    materialized = campaign_dir / facts_attempt["run_dir"] / "workspace" / "input" / "ARASENS"
    assert (materialized / "main-article.txt").read_text(encoding="utf-8") == "source bytes"
    assert (
        json.loads((materialized / "scope-matched-facts.json").read_text(encoding="utf-8"))[
            "schema"
        ]
        == "rob2-kit.scope-matched-facts.v1"
    )
    assert facts_attempt["source_materialization"]["status"] == "verified"


def test_continue_approved_uses_frozen_prompt_and_same_session_without_approving_review(
    tmp_path: Path,
) -> None:
    config, interventions, inputs, runner, _input_root = _campaign_inputs(tmp_path)
    campaign_dir = tmp_path / "campaign"
    launch_args = [
        "--config",
        str(config),
        "--interventions",
        str(interventions),
        "--inputs",
        str(inputs),
        "--campaign-dir",
        str(campaign_dir),
        "--factor",
        "evidence_exposure",
        "--runner",
        str(runner),
    ]
    assert _LAUNCHER["main"](launch_args) == 0
    launch = json.loads((campaign_dir / "launch.json").read_text(encoding="utf-8"))

    # The launcher does not approve Review. The runner refuses to continue until
    # the researcher has approved each isolated workspace.
    assert _LAUNCHER["main"]([*launch_args, "--continue-approved"]) == 1
    launch = json.loads((campaign_dir / "launch.json").read_text(encoding="utf-8"))
    assert all(
        row["continuations"][-1]["launch_status"] == "runner_failed"
        and not (campaign_dir / row["run_dir"] / "phase-2.jsonl").exists()
        for row in launch["attempts"]
    )

    for row in launch["attempts"]:
        (campaign_dir / row["run_dir"] / "workspace" / "researcher-approved").touch()
    assert _LAUNCHER["main"]([*launch_args, "--continue-approved"]) == 0
    launch = json.loads((campaign_dir / "launch.json").read_text(encoding="utf-8"))
    assert all(row["execution_state"] == "succeeded" for row in launch["attempts"])
    for row in launch["attempts"]:
        continuation = row["continuations"][-1]
        command = continuation["command"]
        assert command[command.index("--session") + 1] == "codex-session-fixed"
        assert command[command.index("--prompt") + 1] == str(
            (campaign_dir / "continuation.txt").resolve()
        )
        assert "--case" not in command
        assert "rob2 review" not in " ".join(command)
        assert continuation["trace_retained"]
        assert continuation["trace_identity"].startswith("sha256:")


@pytest.mark.parametrize(
    ("field", "tampered_value"),
    [
        ("run_dir", "../../outside-run"),
        ("run_dir", "{absolute_run}"),
        ("continuation_prompt_file", "../../outside-prompt.txt"),
        ("continuation_prompt_file", "{absolute_prompt}"),
    ],
)
def test_continue_rejects_tampered_campaign_paths(
    tmp_path: Path, field: str, tampered_value: str
) -> None:
    config_path, interventions_path, inputs_path, runner, _input_root = _campaign_inputs(tmp_path)
    campaign_dir = tmp_path / "campaign"
    launch_args = [
        "--config",
        str(config_path),
        "--interventions",
        str(interventions_path),
        "--inputs",
        str(inputs_path),
        "--campaign-dir",
        str(campaign_dir),
        "--factor",
        "evidence_exposure",
        "--runner",
        str(runner),
    ]
    assert _LAUNCHER["main"](launch_args) == 0
    outside_run = tmp_path / "outside-run"
    outside_run.mkdir()
    sentinel = outside_run / "execution.json"
    sentinel.write_text("unchanged", encoding="utf-8")
    outside_prompt = tmp_path / "outside-prompt.txt"
    outside_prompt.write_bytes(b"Continue.\n")
    value = tampered_value.format(
        absolute_run=str(outside_run), absolute_prompt=str(outside_prompt)
    )
    launch_path = campaign_dir / "launch.json"
    launch = json.loads(launch_path.read_text(encoding="utf-8"))
    if field == "run_dir":
        launch["attempts"][0][field] = value
    else:
        launch[field] = value
    launch_path.write_text(json.dumps(launch), encoding="utf-8")

    with pytest.raises(ValueError):
        _LAUNCHER["continue_approved_campaign"](
            campaign_dir.resolve(),
            config=json.loads(config_path.read_text(encoding="utf-8")),
            interventions=json.loads(interventions_path.read_text(encoding="utf-8")),
            inputs=json.loads(inputs_path.read_text(encoding="utf-8")),
            runner=runner,
            factor="evidence_exposure",
            runner_call=lambda *_args, **_kwargs: pytest.fail("unsafe continuation was invoked"),
        )

    assert sentinel.read_text(encoding="utf-8") == "unchanged"
    assert outside_prompt.read_bytes() == b"Continue.\n"


def test_campaign_rejects_changed_bytes_for_a_shared_source(tmp_path: Path) -> None:
    config, interventions, inputs, runner, input_root = _campaign_inputs(tmp_path)
    baseline_dir = input_root / "baseline"
    treatment_dir = input_root / "treatment"
    baseline_dir.mkdir()
    treatment_dir.mkdir()
    case_rows = json.loads(inputs.read_text(encoding="utf-8"))["runs"]
    baseline_case = json.loads((input_root / "case-0.json").read_text(encoding="utf-8"))
    treatment_case = json.loads((input_root / "case-1.json").read_text(encoding="utf-8"))
    (baseline_dir / "case.json").write_text(json.dumps(baseline_case), encoding="utf-8")
    (treatment_dir / "case.json").write_text(json.dumps(treatment_case), encoding="utf-8")
    (baseline_dir / "main-article.txt").write_text("baseline bytes", encoding="utf-8")
    (treatment_dir / "main-article.txt").write_text("changed bytes", encoding="utf-8")
    (treatment_dir / "decisive-passages.txt").write_text("additional", encoding="utf-8")
    case_rows[0]["case_file"] = "baseline/case.json"
    case_rows[1]["case_file"] = "treatment/case.json"
    inputs.write_text(
        json.dumps({"schema": "rob2-kit.development-comparison-inputs.v1", "runs": case_rows}),
        encoding="utf-8",
    )
    campaign_dir = tmp_path / "campaign"

    with pytest.raises(SystemExit) as error:
        _LAUNCHER["main"](
            [
                "--config",
                str(config),
                "--interventions",
                str(interventions),
                "--inputs",
                str(inputs),
                "--campaign-dir",
                str(campaign_dir),
                "--factor",
                "evidence_exposure",
                "--runner",
                str(runner),
                "--dry-run",
            ]
        )

    assert error.value.code == 2
    assert not campaign_dir.exists()


def test_fact_binding_launch_materializes_verified_facts_source(tmp_path: Path) -> None:
    config, interventions, inputs, runner, _input_root = _campaign_inputs(
        tmp_path, factor="fact_binding"
    )
    campaign_dir = tmp_path / "campaign"

    result = _LAUNCHER["main"](
        [
            "--config",
            str(config),
            "--interventions",
            str(interventions),
            "--inputs",
            str(inputs),
            "--campaign-dir",
            str(campaign_dir),
            "--factor",
            "fact_binding",
            "--runner",
            str(runner),
        ]
    )

    assert result == 0
    launch = json.loads((campaign_dir / "launch.json").read_text(encoding="utf-8"))
    assert launch["selected_pair"] == "fact-binding"
    assert {row["arm_id"] for row in launch["attempts"]} == {"baseline", "facts"}
    fact_rows = [row for row in launch["attempts"] if row["arm_id"] == "facts"]
    assert len(fact_rows) == 2
    assert all(
        any(source["name"] == "scope-matched-facts.json" for source in row["source_expectations"])
        and row["source_materialization"] == {"status": "verified", "source_count": 2}
        for row in fact_rows
    )


@pytest.mark.parametrize("forbidden", ["prediction", "overall_label", "answer"])
def test_fact_binding_rejects_answer_fields(tmp_path: Path, forbidden: str) -> None:
    config, interventions, inputs, runner, input_root = _campaign_inputs(
        tmp_path, factor="fact_binding"
    )
    facts_path = input_root / "scope-matched-facts.json"
    facts = json.loads(facts_path.read_text(encoding="utf-8"))
    facts[forbidden] = "low"
    facts_path.write_text(json.dumps(facts), encoding="utf-8")

    with pytest.raises(SystemExit) as error:
        _LAUNCHER["main"](
            [
                "--config",
                str(config),
                "--interventions",
                str(interventions),
                "--inputs",
                str(inputs),
                "--campaign-dir",
                str(tmp_path / "campaign"),
                "--factor",
                "fact_binding",
                "--runner",
                str(runner),
                "--dry-run",
            ]
        )

    assert error.value.code == 2
    assert not (tmp_path / "campaign").exists()
