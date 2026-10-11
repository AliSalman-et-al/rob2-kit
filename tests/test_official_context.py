"""Complete source capture and actual bounded official-guidance delivery."""

import json
import sqlite3
from pathlib import Path

from support.rob2 import _assessment_workspace, _call

from rob2_kit.application._state import _state
from rob2_kit.application.domains import _official_guidance_recovery
from rob2_kit.packs import SCIENTIFIC_PACK


def test_background_and_faq_wording_preserve_source_versions_and_scope() -> None:
    background = json.loads(
        Path("tests/fixtures/official-guidance-audit-2019/background.json").read_text(
            encoding="utf-8"
        )
    )
    faq = json.loads(
        Path("tests/fixtures/official-guidance-audit-2019/faq.json").read_text(encoding="utf-8")
    )
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
    current_faq = json.loads(
        Path("tests/fixtures/official-guidance-audit-2019/faq-20261008.json").read_text(
            encoding="utf-8"
        )
    )
    for record in [*faq["sections"], *current_faq["sections"]]:
        official = by_locator[record["source_locator"]]
        assert official.source_url == record["source_url"]
        assert official.guidance.source_excerpt == record["source_excerpt"]
        assert official.guidance.source_sha256 == record["source_sha256"]
        assert official.guidance.version == record["version"]
        assert len(official.question_ids) == 1


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


def test_box9_continuation_preserves_words_and_reading_order() -> None:
    capture = json.loads(
        Path("tests/fixtures/official-guidance-audit-2019/background.json").read_text(
            encoding="utf-8"
        )
    )
    original49, original50 = capture["original_box9_page_captures"]
    joined, remaining = capture["sections"][2:4]
    tail = original50["text"][original50["text"].index("complexity. Furthermore,") :]
    assert joined["text"] == original49["text"].rstrip() + " " + tail
    assert remaining["text"] + tail == original50["text"]
    assert "substantial complexity." in joined["normalized_excerpt"]
    assert "Consideration of risk of bias in this domain depends on" not in tail


def test_runtime_profiler_reassembles_the_same_official_core() -> None:
    from scripts.profile_domain_context_delivery import _reconstruct

    core = json.loads(json.dumps(_official_guidance_recovery("domain:selection")))
    pages = {}
    for index, section in enumerate(core["sections"]):
        pages[index] = {
            "data": {
                "context_page": {"index": index, "sections": [{"section": "official_guidance"}]},
                "official_guidance": {
                    "pack": core["pack"],
                    "sections": [section],
                    "complete": False,
                    "next_cursor": "next",
                },
            }
        }
    recovered = _reconstruct(pages)
    assert recovered is not None
    assert recovered["official_guidance"] == core
