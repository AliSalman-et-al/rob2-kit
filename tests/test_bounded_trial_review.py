from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from rob2_kit.interfaces.mcp import server
from rob2_kit.interfaces.mcp.contracts import normalize

_DOMAIN = "domain:randomization"
_QUESTION = "sq:randomization:sequence"
_SELECTOR = {"domain_id": _DOMAIN, "question_id": _QUESTION}
_LIMIT = 24_000


def _identity(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def _review(*, reason: str = "", justification: str | None = None, evidence_count: int = 0) -> dict:
    answer = {
        "question_id": _QUESTION,
        "question": "Was the allocation sequence generated randomly?",
        "driver": True,
        "answer": "no_information",
    }
    if justification is not None:
        answer["justification"] = justification
    if evidence_count:
        answer["evidence"] = [
            {"handle": f"eh_{index:016x}", "identity": _identity(f"evidence-{index}")}
            for index in range(evidence_count)
        ]
    value = {
        "outcome": "success",
        "phase": "assessment",
        "state_revision": 7,
        "authoritative_wording": "Inspect the current workflow status.",
        "review": {
            "identity": _identity("review"),
            "trial_id": "synthetic-trial",
            "result_identity": _identity("result"),
            "checkpoint_ids": [_identity("checkpoint")],
            "disposition": "failed" if reason else "assessed",
            "reason": reason or None,
        },
        "domain_findings": []
        if reason
        else [
            {
                "domain_id": _DOMAIN,
                "checkpoint_identity": _identity("checkpoint"),
                "judgment": "some_concerns",
                "answers": [answer],
            }
        ],
    }
    return server._validate_response("review_trial", normalize("review_trial", value))


def _project(
    receipt: dict,
    root: Path,
    *,
    cursor: str | None = None,
    selector: dict[str, str] | None = None,
    persist: bool = False,
) -> dict:
    return server._project_review_trial(
        receipt, cursor=cursor, selector=selector, root=root, persist=persist
    )


def _collect(
    receipt: dict,
    root: Path,
    *,
    cursor: str | None = None,
    first: dict | None = None,
    selector: dict[str, str] | None = None,
) -> str:
    fragments = []
    offset = 0
    total = None
    for index in range(32):
        if index == 0 and first is not None:
            response = first
        else:
            assert cursor is not None
            response = _project(receipt, root, cursor=cursor, selector=selector)
        page = response["data"]["review_page"]
        assert page["mode"] == "fragment"
        assert page["complete"] is False
        assert page["offset_unit"] == "unicode_codepoints"
        assert page["offset"] == offset
        total = page["total"] if total is None else total
        assert page["total"] == total
        assert page["fragment"]
        assert server._review_transport_bytes(response) <= _LIMIT
        fragments.append(page["fragment"])
        offset += len(page["fragment"])
        cursor = page.get("next_cursor")
        if cursor is None:
            break
    else:
        pytest.fail("review fragments did not terminate")
    assert offset == total
    return "".join(fragments)


def test_small_review_keeps_legacy_shape_and_selected_bound_includes_typed_defaults(
    tmp_path: Path,
) -> None:
    root = server._root(tmp_path)
    small = _review()
    assert _project(small, root) == small
    assert "review_page" not in small["data"]
    for length in range(21_500, 23_901, 100):
        receipt = _review(justification="x" * length)
        selected = _project(receipt, root, selector=_SELECTOR, persist=True)
        assert server._review_transport_bytes(selected) <= _LIMIT
        if selected["data"]["review_page"]["mode"] == "complete":
            assert (
                selected["data"]["domain_findings"][0]["answers"][0]
                == receipt["data"]["domain_findings"][0]["answers"][0]
            )
        else:
            assert (
                json.loads(_collect(receipt, root, first=selected, selector=_SELECTOR))
                == receipt["data"]["domain_findings"][0]["answers"][0]
            )


@pytest.mark.parametrize("kind", ["terminal_reason", "evidence"])
def test_oversized_unicode_reason_and_evidence_are_explicit_and_recoverable(
    tmp_path: Path, kind: str
) -> None:
    text = 'é🧪"\\\n' * 5_000
    receipt = _review(reason=text) if kind == "terminal_reason" else _review(evidence_count=360)
    root = server._root(tmp_path)
    summary = _project(receipt, root, persist=True)
    page = summary["data"]["review_page"]
    assert page["mode"] == "summary"
    assert page["complete"] is False
    assert server._review_transport_bytes(summary) <= _LIMIT
    field = "review_reason" if kind == "terminal_reason" else "evidence"
    assert field in page["deferred_fields"]
    if kind == "terminal_reason":
        assert page["counts"]["review_reason_characters"] == len(text)
    else:
        answer = summary["data"]["domain_findings"][0]["answers"][0]
        detail = answer["detail_projection"]
        assert detail["counts"]["evidence"] == 360
        assert "evidence" in detail["deferred_fields"]
        assert detail["counts"]["unknowns"] == 0
        assert "unknowns" not in detail["deferred_fields"]
        assert answer["evidence"] == []
    assert page["stable_recovery"]["operation"] == "review_trial"
    assert json.loads(_collect(receipt, root, cursor=page["stable_recovery"]["cursor"])) == receipt


def test_selected_unicode_fragments_preserve_snapshot_and_reject_changed_review_scope(
    tmp_path: Path,
) -> None:
    text = 'é🧪"\\\n' * 7_000
    receipt = _review(justification=text)
    root = server._root(tmp_path)
    first = _project(receipt, root, selector=_SELECTOR, persist=True)
    page = first["data"]["review_page"]
    assert page["mode"] == "fragment"
    assert page["target"] == "answer_finding"
    assert page["selector"] == _SELECTOR
    assert (
        json.loads(_collect(receipt, root, first=first, selector=_SELECTOR))
        == receipt["data"]["domain_findings"][0]["answers"][0]
    )
    cursor = page["next_cursor"]
    changed = json.loads(json.dumps(receipt))
    changed["head"]["state_revision"] += 1
    # Reading/search revisions leave the immutable scientific review recoverable.
    assert (
        _project(changed, root, cursor=cursor)["data"]["review_page"]["snapshot_digest"]
        == page["snapshot_digest"]
    )
    changed["data"]["review"]["identity"] = _identity("corrected-review")
    with pytest.raises(ValueError, match="review_cursor_stale"):
        _project(changed, root, cursor=cursor)
    other_trial = json.loads(json.dumps(receipt))
    other_trial["data"]["review"]["trial_id"] = "other-trial"
    with pytest.raises(ValueError, match="review_cursor_invalid"):
        _project(other_trial, root, cursor=cursor)
    with pytest.raises(ValueError, match="review_cursor_invalid"):
        _project(receipt, root, cursor=cursor, selector={"domain_id": _DOMAIN})
    with server._db(root, "derivative.sqlite3") as connection:
        connection.execute("DELETE FROM review_views")
    with pytest.raises(ValueError, match="review_cursor_expired.*restart review_trial"):
        _project(receipt, root, cursor=cursor)
