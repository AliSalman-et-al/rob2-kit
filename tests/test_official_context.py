"""Complete source capture and actual bounded official-guidance delivery."""

import json
import sqlite3
from pathlib import Path

import pytest
from support.rob2 import _assessment_workspace, _call

from rob2_kit.application._state import _state
from rob2_kit.application.domains import _official_guidance_recovery
from rob2_kit.interfaces.mcp.server import _domain_context_transport_bytes
from rob2_kit.packs import SCIENTIFIC_PACK, load_scientific_pack


def test_complete_question_capture_and_background_are_pack_bound() -> None:
    capture = json.loads(
        Path("tests/fixtures/official-guidance-audit-2019/complete-elaborations.json").read_text()
    )
    assert len(capture["questions"]) == 22
    by_id = {question.id: question for question in SCIENTIFIC_PACK.questions}
    for record in capture["questions"]:
        official = by_id[record["question_id"]].guidance.official
        assert official.source_excerpt == record["normalized_excerpt"]
        assert official.source_locator == record["source_locator"]
        assert official.source_sha256 == capture["source_sha256"]
        assert (
            " ".join(" ".join(block["text"] for block in record["blocks"]).split())
            == official.source_excerpt
        )
    altered = SCIENTIFIC_PACK.model_dump(mode="json")
    altered["official_sections"][0]["guidance"]["source_excerpt"] += " altered"
    with pytest.raises(ValueError, match="hash"):
        load_scientific_pack(altered)


def test_background_and_faq_wording_preserve_source_versions_and_scope() -> None:
    background = json.loads(
        Path("tests/fixtures/official-guidance-audit-2019/background.json").read_text()
    )
    faq = json.loads(Path("tests/fixtures/official-guidance-audit-2019/faq.json").read_text())
    by_locator = {
        section.guidance.source_locator: section
        for section in SCIENTIFIC_PACK.official_sections or ()
    }
    for record in background["sections"]:
        official = by_locator[record["source_locator"]]
        assert official.domain_id == record["domain_id"]
        assert official.guidance.source_excerpt == " ".join(record["text"].split())
        assert official.guidance.version == background["version"]
        assert official.guidance.source_sha256 == background["source_sha256"]
    for record in faq["sections"]:
        official = by_locator[record["source_locator"]]
        assert official.source_url == record["source_url"]
        assert official.guidance.source_excerpt == record["source_excerpt"]
        assert official.guidance.source_sha256 == record["source_sha256"]
        assert official.guidance.version == record["version"]
        assert len(official.question_ids) == 1


@pytest.mark.parametrize("budget", [16_384, 32_768])
def test_native_pages_deliver_complete_official_core_once(tmp_path: Path, budget: int) -> None:
    workspace, _, _ = _assessment_workspace(tmp_path)
    for domain in SCIENTIFIC_PACK.domains:
        page = _call(
            workspace,
            "get_domain_context",
            {"domain_id": domain.id, "max_response_bytes": budget},
            _raw=True,
        )
        sections = []
        questions = []
        while True:
            assert page["outcome"] == "success", page
            wire = {key: value for key, value in page.items() if key != "_image_content"}
            assert _domain_context_transport_bytes(wire) <= budget
            data = page["data"]
            assert "response_framework" not in data
            sections.extend(data.get("official_guidance", {}).get("sections", []))
            questions.extend(data.get("questions", []))
            cursor = data.get("context_page", {}).get("next_cursor")
            if cursor is None:
                break
            # Each call creates a new Client: recovery does not depend on client memory.
            page = _call(workspace, "get_domain_context", {"cursor": cursor}, _raw=True)
        expected = json.loads(json.dumps(_official_guidance_recovery(domain.id)["sections"]))
        assert sections == expected
        assert {question["id"] for question in questions} == set(domain.question_ids)
        assert all("decision_rule" not in question for question in questions)


def test_preserved_previous_pack_view_recovers_without_schema_failure(tmp_path: Path) -> None:
    workspace, _, _ = _assessment_workspace(tmp_path)
    first = _call(workspace, "get_domain_context", {"max_response_bytes": 16_384}, _raw=True)
    cursor = first["data"]["context_page"]["stable_recovery"]["cursor"]
    view_id = cursor.split(".")[1]
    with sqlite3.connect(workspace / ".rob2-kit" / "derivative.sqlite3") as connection:
        raw = connection.execute(
            "SELECT snapshot FROM domain_context_views WHERE view_id=?", (view_id,)
        ).fetchone()[0]
        historical = json.loads(raw)
        historical["data"]["pack"]["content_hash"] = (
            "sha256:b7da8a956f8c35edb26a62681561ce8f2c6849259dcd97fbad88df4973aa89a1"
        )
        historical["data"]["guidance_profile"] = "official_d3_prototype"
        historical_bytes = json.dumps(historical).encode()
        connection.execute(
            "UPDATE domain_context_views SET snapshot=? WHERE view_id=?",
            (historical_bytes, view_id),
        )
    canonical_before = _state(workspace)
    recovered = _call(workspace, "get_domain_context", {"cursor": cursor}, _raw=True)
    assert recovered["outcome"] == "condition"
    assert recovered["condition"]["code"] == "domain_context_cursor_stale"
    assert _state(workspace) == canonical_before
    with sqlite3.connect(workspace / ".rob2-kit" / "derivative.sqlite3") as connection:
        assert (
            connection.execute(
                "SELECT snapshot FROM domain_context_views WHERE view_id=?", (view_id,)
            ).fetchone()[0]
            == historical_bytes
        )
