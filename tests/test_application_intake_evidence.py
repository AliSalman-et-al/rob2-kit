from __future__ import annotations

import os
import subprocess
from pathlib import Path

import httpx
import pymupdf
import pytest

from rob2_kit.application import intake
from rob2_kit.application._state import _db, _reserved_role
from rob2_kit.application.evidence import (
    _search_receipt,
    read_pages,
    search_sources,
    select_text_evidence,
)
from rob2_kit.application.intake import prepare_batch
from rob2_kit.workflow_models import TrialDeclaration


def test_registry_response_is_a_searchable_captured_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = {
        "protocolSection": {
            "identificationModule": {
                "nctId": "NCT00000001",
                "officialTitle": "Example randomized trial",
            },
            "designModule": {
                "designInfo": {"allocation": "RANDOMIZED"},
                "enrollmentInfo": {"count": 120},
            },
            "contactsLocationsModule": {"overallOfficials": []},
        },
        "derivedSection": {"miscInfoModule": {"versionHolder": "2026-08-27"}},
        "hasResults": True,
        "studyMethod": "The method of permuted blocks will be used for randomization.",
    }

    def response(*_args: object, **_kwargs: object) -> httpx.Response:
        return httpx.Response(
            200,
            json=payload,
            request=httpx.Request("GET", "https://clinicaltrials.gov/api/v2/studies/NCT00000001"),
        )

    monkeypatch.setattr(intake.httpx, "get", response)
    trial = tmp_path / "input" / "trial"
    trial.mkdir(parents=True)
    (trial / "sources.toml").write_text('nct = "NCT00000001"\n', encoding="utf-8")

    prepared = prepare_batch(
        tmp_path,
        [TrialDeclaration(id="trial", label="trial", requested_outcome="trial outcome")],
        expected_revision=0,
    )

    assert not any(
        condition["code"] == "no_supported_sources" for condition in prepared["conditions"]
    )
    [source] = prepared["trials"][0]["sources"]
    assert source["role"] == "registry"
    assert source["origin"] == "registry"
    assert source["logical_path"] == "registry/NCT00000001.json"
    captured = next((tmp_path / ".rob2-kit" / "sources" / "trial").glob(f"{source['id']}.bin"))
    assert captured.read_bytes().startswith(b"{\n")
    registry_page = read_pages(tmp_path, "trial", source["id"], [1])["pages"][0]
    assert len(registry_page["text"].splitlines()) > 1
    (tmp_path / ".rob2-kit" / "derivative.sqlite3").unlink()
    found = search_sources(tmp_path, "trial", "permuted blocks")
    assert found["outcome"] == "success"
    hit = found["hits"][0]
    assert hit["source_id"] == source["id"]
    assert hit["start_line"] == hit["end_line"]
    anchored_page = read_pages(tmp_path, "trial", source["id"], [hit["page"]])["pages"][0]
    anchored_line = anchored_page["text"].splitlines()[hit["start_line"] - 1]
    assert 'studyMethod: "The method of permuted blocks' in anchored_line
    selected = select_text_evidence(
        tmp_path,
        "trial",
        source["id"],
        1,
        "The method of permuted blocks will be used for randomization.",
    )
    assert "permuted blocks" in selected["evidence"]["quote"]


def _source_for_text(tmp_path: Path, text: str) -> tuple[Path, dict[str, object]]:
    (tmp_path / "input" / "trial").mkdir(parents=True)
    (tmp_path / "input" / "trial" / "main.txt").write_bytes(text.encode("utf-8"))
    prepared = prepare_batch(
        tmp_path,
        [TrialDeclaration(id="trial", label="trial", requested_outcome="trial outcome")],
        expected_revision=0,
    )
    source = prepared["trials"][0]["sources"][0]
    return tmp_path, source


def test_prepare_batch_ignores_hidden_files_and_directories_but_keeps_nested_docs(
    tmp_path: Path,
) -> None:
    trial = tmp_path / "input" / "trial"
    (trial / "nested").mkdir(parents=True)
    (trial / "nested" / "normal.txt").write_text("normal", encoding="utf-8")
    (trial / "nested" / ".hidden.md").write_text("hidden", encoding="utf-8")
    (trial / ".claude").mkdir()
    (trial / ".claude" / "skill.md").write_text("hidden", encoding="utf-8")
    (trial / ".mcp-transient.json").write_text("{}", encoding="utf-8")

    prepared = prepare_batch(
        tmp_path,
        [TrialDeclaration(id="trial", label="trial", requested_outcome="trial outcome")],
        expected_revision=0,
    )

    paths = [source["logical_path"] for source in prepared["trials"][0]["sources"]]
    assert paths == ["nested/normal.txt"]


def test_prepare_batch_does_not_follow_symlinked_source_files(tmp_path: Path) -> None:
    trial = tmp_path / "input" / "trial"
    trial.mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("not authorized", encoding="utf-8")
    link = trial / "linked.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("file symlinks are unavailable on this platform")

    prepared = prepare_batch(
        tmp_path,
        [TrialDeclaration(id="trial", label="trial", requested_outcome="trial outcome")],
        expected_revision=0,
    )

    assert prepared["trials"][0]["sources"] == []


def test_prepare_batch_rejects_symlinked_source_manifest(tmp_path: Path) -> None:
    trial = tmp_path / "input" / "trial"
    trial.mkdir(parents=True)
    outside = tmp_path / "outside.toml"
    outside.write_text('roles = { "main.txt" = "protocol" }\n', encoding="utf-8")
    manifest = trial / "sources.toml"
    try:
        manifest.symlink_to(outside)
    except OSError:
        pytest.skip("file symlinks are unavailable on this platform")
    (trial / "main.txt").write_text("captured source", encoding="utf-8")

    with pytest.raises(ValueError, match="sources.toml is outside the Trial directory"):
        prepare_batch(
            tmp_path,
            [TrialDeclaration(id="trial", label="trial", requested_outcome="outcome")],
            expected_revision=0,
        )


def test_prepare_batch_rejects_symlinked_internal_trial_directory(tmp_path: Path) -> None:
    trial = tmp_path / "input" / "trial"
    trial.mkdir(parents=True)
    (trial / "main.txt").write_text("captured source", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    internal_sources = tmp_path / ".rob2-kit" / "sources"
    internal_sources.mkdir(parents=True)
    link = internal_sources / "trial"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable on this platform")

    with pytest.raises(ValueError, match="must not be a symlink or junction"):
        prepare_batch(
            tmp_path,
            [TrialDeclaration(id="trial", label="trial", requested_outcome="outcome")],
            expected_revision=0,
        )


@pytest.mark.skipif(os.name != "nt", reason="directory junctions are a Windows boundary")
def test_prepare_batch_rejects_junctioned_input_directory(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    (outside / "Trial").mkdir(parents=True)
    (outside / "Trial" / "main.txt").write_text("not authorized", encoding="utf-8")
    input_root = tmp_path / "input"
    result = subprocess.run(
        ["cmd", "/d", "/c", "mklink", "/J", str(input_root), str(outside)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip("directory junctions are unavailable on this platform")

    with pytest.raises(ValueError, match="input directory is not available"):
        prepare_batch(
            tmp_path,
            [TrialDeclaration(id="trial", label="Trial", requested_outcome="outcome")],
            expected_revision=0,
        )


def test_prepare_batch_resolves_input_directory_from_trial_label(tmp_path: Path) -> None:
    trial = tmp_path / "input" / "Trial"
    trial.mkdir(parents=True)
    (trial / "main.txt").write_text("captured source", encoding="utf-8")
    declaration = TrialDeclaration(
        id="trial",
        label="Trial",
        requested_outcome="requested outcome",
    )

    prepared = prepare_batch(tmp_path, [declaration], expected_revision=0)
    assert [source["logical_path"] for source in prepared["trials"][0]["sources"]] == ["main.txt"]


def test_prepare_batch_rejects_two_declarations_for_one_trial_directory(tmp_path: Path) -> None:
    trial = tmp_path / "input" / "Trial"
    trial.mkdir(parents=True)
    (trial / "main.txt").write_text("captured source", encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate trial directory"):
        prepare_batch(
            tmp_path,
            [
                TrialDeclaration(id="first", label="Trial", requested_outcome="outcome"),
                TrialDeclaration(id="second", label="Trial", requested_outcome="outcome"),
            ],
            expected_revision=0,
        )


def test_search_orders_main_article_before_protocol_and_replays_that_order(
    tmp_path: Path,
) -> None:
    trial = tmp_path / "input" / "trial"
    trial.mkdir(parents=True)
    (trial / "z_protocol.txt").write_text("shared finding", encoding="utf-8")
    (trial / "a_main.txt").write_text("shared finding", encoding="utf-8")
    (trial / "sources.toml").write_text(
        'roles = { "z_protocol.txt" = "protocol", "a_main.txt" = "main_article" }\n',
        encoding="utf-8",
    )
    prepared = prepare_batch(
        tmp_path,
        [TrialDeclaration(id="trial", label="trial", requested_outcome="trial outcome")],
        expected_revision=0,
    )

    result = search_sources(tmp_path, "trial", "shared", limit=1)
    source_by_id = {source["id"]: source for source in prepared["trials"][0]["sources"]}
    main_id = next(
        source_id for source_id, source in source_by_id.items() if source["role"] == "main_article"
    )

    assert result["total_matches"] == 2
    assert result["truncated"] is True
    assert result["hits"][0]["source_id"] == main_id
    assert result["hits"][0]["source_role"] == "main_article"
    assert result["hits"][0]["source_label"] == "a_main.txt"
    assert result["search_receipt"]["sources"][0]["id"] == main_id
    assert (
        result["search_receipt"]["sources"][0]["id"] != result["search_receipt"]["sources"][1]["id"]
    )
    replayed = _search_receipt(tmp_path, result["search_receipt"]["handle"])
    assert replayed["hits"] == result["search_receipt"]["hits"]


def test_search_defaults_to_any_for_exploratory_concepts(tmp_path: Path) -> None:
    trial = tmp_path / "input" / "trial"
    trial.mkdir(parents=True)
    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "randomized")
    document.new_page().insert_text((72, 72), "concealment")
    (trial / "main.pdf").write_bytes(document.tobytes())
    document.close()
    prepare_batch(
        tmp_path,
        [TrialDeclaration(id="trial", label="trial", requested_outcome="trial outcome")],
        expected_revision=0,
    )

    result = search_sources(tmp_path, "trial", "randomized concealment")

    assert [hit["page"] for hit in result["hits"]] == [1, 2]
    assert result["search_receipt"]["mode"] == "any"


def test_broad_search_prefers_source_priority_then_term_coverage(tmp_path: Path) -> None:
    trial = tmp_path / "input" / "trial"
    trial.mkdir(parents=True)
    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "randomization")
    document.new_page().insert_text((72, 72), "randomization permuted")
    (trial / "a_main.pdf").write_bytes(document.tobytes())
    document.close()
    (trial / "z_supplement.txt").write_text("randomization permuted blocks", encoding="utf-8")
    (trial / "sources.toml").write_text(
        'roles = { "a_main.pdf" = "main_article", "z_supplement.txt" = "supplement" }\n',
        encoding="utf-8",
    )
    prepared = prepare_batch(
        tmp_path,
        [TrialDeclaration(id="trial", label="trial", requested_outcome="outcome")],
        expected_revision=0,
    )

    result = search_sources(
        tmp_path,
        "trial",
        "randomization permuted blocks",
        mode="any",
        limit=3,
    )
    main_id = next(
        source["id"]
        for source in prepared["trials"][0]["sources"]
        if source["role"] == "main_article"
    )
    supplement_id = next(
        source["id"]
        for source in prepared["trials"][0]["sources"]
        if source["role"] == "supplement"
    )

    assert result["total_matches"] == 3
    assert result["truncated"] is False
    assert [(hit["source_id"], hit["page"]) for hit in result["hits"]] == [
        (main_id, 2),
        (main_id, 1),
        (supplement_id, 1),
    ]
    replayed = _search_receipt(tmp_path, result["search_receipt"]["handle"])
    assert replayed["hits"] == result["search_receipt"]["hits"]


def test_broad_search_uses_source_priority_for_equal_coverage(tmp_path: Path) -> None:
    trial = tmp_path / "input" / "trial"
    trial.mkdir(parents=True)
    (trial / "a_main.txt").write_text("permuted blocks", encoding="utf-8")
    (trial / "z_protocol.txt").write_text("permuted blocks", encoding="utf-8")
    (trial / "sources.toml").write_text(
        'roles = { "a_main.txt" = "main_article", "z_protocol.txt" = "protocol" }\n',
        encoding="utf-8",
    )
    prepared = prepare_batch(
        tmp_path,
        [TrialDeclaration(id="trial", label="trial", requested_outcome="outcome")],
        expected_revision=0,
    )

    result = search_sources(tmp_path, "trial", "permuted blocks", mode="any", limit=1)
    main_id = next(
        source["id"]
        for source in prepared["trials"][0]["sources"]
        if source["role"] == "main_article"
    )

    assert result["hits"][0]["source_id"] == main_id


def test_prefix_search_prefers_source_priority_then_distinct_prefix_coverage(
    tmp_path: Path,
) -> None:
    trial = tmp_path / "input" / "trial"
    trial.mkdir(parents=True)
    (trial / "a_main.txt").write_text("Random allocation", encoding="utf-8")
    (trial / "z_protocol.txt").write_text(
        "Permuted blocks were used for subject randomization.", encoding="utf-8"
    )
    (trial / "sources.toml").write_text(
        'roles = { "a_main.txt" = "main_article", "z_protocol.txt" = "protocol" }\n',
        encoding="utf-8",
    )
    prepared = prepare_batch(
        tmp_path,
        [TrialDeclaration(id="trial", label="trial", requested_outcome="outcome")],
        expected_revision=0,
    )

    result = search_sources(
        tmp_path,
        "trial",
        "random permut",
        mode="prefix",
        limit=1,
    )
    main_id = next(
        source["id"]
        for source in prepared["trials"][0]["sources"]
        if source["role"] == "main_article"
    )

    assert result["total_matches"] == 2
    assert result["truncated"] is True
    assert result["hits"][0]["source_id"] == main_id
    replayed = _search_receipt(tmp_path, result["search_receipt"]["handle"])
    assert replayed["hits"] == result["search_receipt"]["hits"]


def test_search_keeps_supplement_only_results_discoverable(tmp_path: Path) -> None:
    trial = tmp_path / "input" / "trial"
    trial.mkdir(parents=True)
    (trial / "supplement.txt").write_text("supplementary finding", encoding="utf-8")
    prepare_batch(
        tmp_path,
        [TrialDeclaration(id="trial", label="trial", requested_outcome="trial outcome")],
        expected_revision=0,
    )

    result = search_sources(tmp_path, "trial", "supplementary")

    assert result["total_matches"] == 1
    assert result["hits"][0]["page"] == 1


def test_disclosure_filename_defaults_to_other_role(tmp_path: Path) -> None:
    trial = tmp_path / "input" / "trial"
    trial.mkdir(parents=True)
    (trial / "disclosure.txt").write_text("captured source", encoding="utf-8")
    prepared = prepare_batch(
        tmp_path,
        [TrialDeclaration(id="trial", label="trial", requested_outcome="trial outcome")],
        expected_revision=0,
    )

    assert prepared["trials"][0]["sources"][0]["role"] == "other"
    assert _reserved_role("registry.pdf") == "registry"
    assert _reserved_role("disclosure.pdf") == "other"


def test_select_text_evidence_collapses_newlines_and_keeps_raw_quote(tmp_path: Path) -> None:
    raw = "Median overall survival was 57.6\nmonths in combination."
    _, source = _source_for_text(tmp_path, raw)

    selected = select_text_evidence(
        tmp_path,
        "trial",
        str(source["id"]),
        1,
        "Median overall survival was 57.6 months in combination.",
    )["evidence"]

    assert selected["quote"] == raw
    assert selected["start"] == 0
    assert selected["end"] == len(selected["quote"])


def test_select_text_evidence_accepts_unicode_normalization_and_nbsp(tmp_path: Path) -> None:
    raw = "Café\u00a0benefit was observed."
    _, source = _source_for_text(tmp_path, raw)

    selected = select_text_evidence(
        tmp_path,
        "trial",
        str(source["id"]),
        1,
        "Cafe\u0301 benefit was observed.",
    )["evidence"]

    assert selected["quote"] == "Café benefit was observed."


def test_select_text_evidence_accepts_typographic_quote_normalization(tmp_path: Path) -> None:
    raw = "The “unknown” category was excluded."
    _, source = _source_for_text(tmp_path, raw)

    selected = select_text_evidence(
        tmp_path,
        "trial",
        str(source["id"]),
        1,
        'The "unknown" category was excluded.',
    )["evidence"]

    assert selected["quote"] == 'The "unknown" category was excluded.'


def test_search_and_selection_share_case_soft_hyphen_and_dash_normalization(
    tmp_path: Path,
) -> None:
    raw = "The Doce\u00adtaxel Group reported a Hazard Ratio of 0.61\u20130.80."
    workspace, source = _source_for_text(tmp_path, raw)

    search = search_sources(workspace, "trial", "docetaxel hazard ratio")
    selected = select_text_evidence(
        workspace,
        "trial",
        str(source["id"]),
        search["hits"][0]["page"],
        "the docetaxel group reported a hazard ratio of 0.61-0.80.",
    )["evidence"]

    projected = "The Docetaxel Group reported a Hazard Ratio of 0.61-0.80."
    assert selected["quote"] == projected
    assert selected["start"] == 0
    assert selected["end"] == len(projected)


@pytest.mark.parametrize("hyphen", ["-", "\u2010", "\u2011", "\u2013"])
def test_select_text_evidence_accepts_line_end_word_hyphenation(
    tmp_path: Path, hyphen: str
) -> None:
    raw = f"The overall sur{hyphen}\nvival result improved."
    workspace, source = _source_for_text(tmp_path, raw)
    search = search_sources(workspace, "trial", "overall survival", mode="phrase")

    selected = select_text_evidence(
        workspace,
        "trial",
        str(source["id"]),
        search["hits"][0]["page"],
        "The overall survival result improved.",
    )["evidence"]

    projected = "The overall sur-\nvival result improved."
    assert selected["quote"] == projected
    assert selected["start"] == 0
    assert selected["end"] == len(projected)


def test_select_text_evidence_maps_semantic_hyphen_to_real_source_line_wrap(
    tmp_path: Path,
) -> None:
    raw = "The castration-\nresistant population was stratified."
    workspace, source = _source_for_text(tmp_path, raw)

    selected = select_text_evidence(
        workspace,
        "trial",
        str(source["id"]),
        1,
        "The castration-resistant population was stratified.",
    )["evidence"]

    assert selected["quote"] == raw
    assert selected["start"] == 0
    assert selected["end"] == len(raw)


def test_select_text_evidence_does_not_make_semantic_hyphens_optional(
    tmp_path: Path,
) -> None:
    workspace, source = _source_for_text(
        tmp_path, "The castrationresistant population was stratified."
    )

    with pytest.raises(ValueError, match="not an exact page selection"):
        select_text_evidence(
            workspace,
            "trial",
            str(source["id"]),
            1,
            "The castration-resistant population was stratified.",
        )


def test_search_derivative_finds_dehyphenated_and_original_forms(tmp_path: Path) -> None:
    raw = "The bio-\nchemical result was retained."
    workspace, _ = _source_for_text(tmp_path, raw)

    dehyphenated = search_sources(workspace, "trial", "biochemical")
    original = search_sources(workspace, "trial", "bio-chemical")
    any_mode = search_sources(workspace, "trial", "bio-chemical", mode="any")
    prefix_mode = search_sources(workspace, "trial", "bio-chemical", mode="prefix")

    assert dehyphenated["hits"][0]["page"] == 1
    assert original["hits"][0]["page"] == 1
    assert any_mode["hits"][0]["page"] == 1
    assert prefix_mode["hits"][0]["page"] == 1
    assert "bio-\nchemical" in dehyphenated["hits"][0]["preview"]


def test_search_hits_issue_read_pages_line_coordinates_from_normalized_span(
    tmp_path: Path,
) -> None:
    raw = "prefix\nThe bio-\nchemical result was retained.\nsuffix"
    workspace, source = _source_for_text(tmp_path, raw)

    result = search_sources(workspace, "trial", "biochemical result", mode="phrase")
    hit = result["hits"][0]
    page = read_pages(workspace, "trial", str(source["id"]), [1])["pages"][0]

    assert (hit["start_line"], hit["end_line"]) == (2, 3)
    assert page["text"].splitlines()[hit["start_line"] - 1] == "The bio-"
    assert page["text"].splitlines()[hit["end_line"] - 1] == "chemical result was retained."


def test_search_maps_fts_punctuation_tokens_back_to_source_lines(tmp_path: Path) -> None:
    raw = "prefix\nComputer-generated random number, stratified 1:1.\nsuffix"
    workspace, _ = _source_for_text(tmp_path, raw)

    result = search_sources(
        workspace,
        "trial",
        "computer-generated random number stratified 1:1",
    )

    assert len(result["hits"]) == 1
    assert (result["hits"][0]["start_line"], result["hits"][0]["end_line"]) == (2, 2)
    assert "Computer-generated" in result["hits"][0]["preview"]


def test_search_maps_fts_diacritic_folding_back_to_source_lines(tmp_path: Path) -> None:
    workspace, _ = _source_for_text(tmp_path, "The café result was retained.")

    result = search_sources(workspace, "trial", "cafe")

    assert len(result["hits"]) == 1
    assert result["hits"][0]["start_line"] == 1


def test_search_and_public_reads_share_the_normalized_page_projection(
    tmp_path: Path,
) -> None:
    raw = "The ﬁnal\u200b\u202e analysis\x00 was complete.\u00ad"
    workspace, source = _source_for_text(tmp_path, raw)

    result = search_sources(workspace, "trial", "final analysis was complete", mode="phrase")
    page = read_pages(workspace, "trial", str(source["id"]), [1])["pages"][0]

    assert result["hits"][0]["page"] == 1
    projected = "The final analysis was complete."
    assert result["hits"][0]["preview"] == projected
    assert page["text"] == projected


def test_phrase_search_does_not_cross_search_variant_boundary(tmp_path: Path) -> None:
    raw = "The bio-\nchemical result was retained."
    workspace, _ = _source_for_text(tmp_path, raw)

    result = search_sources(workspace, "trial", "retained The", mode="phrase")

    assert result["hits"] == []
    assert result["condition"] == "no_hits"


@pytest.mark.parametrize("query", ["bio-chemical result", "bio chemical result"])
def test_phrase_preview_centers_on_dehyphenated_line_wrap(tmp_path: Path, query: str) -> None:
    raw = "prefix " * 80 + "bio-\nchemical result" + " suffix" * 80
    workspace, _ = _source_for_text(tmp_path, raw)

    result = search_sources(workspace, "trial", query, mode="phrase")
    preview = result["hits"][0]["preview"]

    assert "bio-\nchemical result" in preview
    assert not preview.startswith("prefix prefix prefix")


def test_preview_uses_token_boundary_not_substring_match(tmp_path: Path) -> None:
    raw = "antitarget " * 80 + "target result" + " suffix" * 80
    workspace, _ = _source_for_text(tmp_path, raw)

    result = search_sources(workspace, "trial", "target")
    preview = result["hits"][0]["preview"]

    assert "target result" in preview
    assert not preview.startswith("antitarget antitarget")


def test_prefix_preview_scans_past_substring_false_positive(tmp_path: Path) -> None:
    raw = "antitarget " * 80 + "target result" + " suffix" * 80
    workspace, _ = _source_for_text(tmp_path, raw)

    result = search_sources(workspace, "trial", "target", mode="prefix")
    preview = result["hits"][0]["preview"]

    assert "target result" in preview
    assert not preview.startswith("antitarget antitarget")


def test_search_then_select_shared_line_end_hyphenation_keeps_raw_quote(
    tmp_path: Path,
) -> None:
    raw = "The bio-\n_chemical result was retained."
    workspace, source = _source_for_text(tmp_path, raw)

    search = search_sources(workspace, "trial", "bio_chemical", mode="phrase")
    selected = select_text_evidence(
        workspace,
        "trial",
        str(source["id"]),
        search["hits"][0]["page"],
        "bio_chemical result",
    )["evidence"]

    expected = "bio-\n_chemical result"
    assert selected["quote"] == expected
    assert selected["start"] == raw.index(expected)
    assert selected["end"] == selected["start"] + len(expected)


def test_read_pages_rejects_mixed_valid_and_invalid_requests_atomically(
    tmp_path: Path,
) -> None:
    workspace, source = _source_for_text(tmp_path, "page one")

    with pytest.raises(ValueError, match="outside Source"):
        read_pages(workspace, "trial", str(source["id"]), [1, 2])


def test_any_preview_centers_on_the_actual_later_matching_term(tmp_path: Path) -> None:
    raw = "prefix " * 80 + "target phrase" + " suffix" * 80
    workspace, _ = _source_for_text(tmp_path, raw)

    result = search_sources(workspace, "trial", "missing target", mode="any")
    preview = result["hits"][0]["preview"]

    assert "target" in preview
    assert not preview.startswith("prefix prefix prefix")


def test_search_preview_is_match_centered_and_cache_rebuilds_by_version(
    tmp_path: Path,
) -> None:
    raw = "prefix " * 80 + "target phrase" + " suffix" * 80
    workspace, _ = _source_for_text(tmp_path, raw)
    first = search_sources(workspace, "trial", "target phrase")
    preview = first["hits"][0]["preview"]
    assert "target phrase" in preview
    assert not preview.startswith("prefix prefix prefix")
    with _db(workspace, "derivative.sqlite3") as connection:
        assert connection.execute("SELECT normalized_text FROM pages_fts").fetchone()[0] == ""

    with _db(workspace, "derivative.sqlite3") as connection:
        connection.execute("DELETE FROM search_projection_meta WHERE name='version'")

    rebuilt = search_sources(workspace, "trial", "target phrase")
    assert rebuilt["search_receipt"]["identity"] == first["search_receipt"]["identity"]


def test_old_page_projection_recipe_is_rejected_without_rewriting_identity(
    tmp_path: Path,
) -> None:
    workspace, source = _source_for_text(tmp_path, "captured text")
    with _db(workspace, "canonical.sqlite3") as connection:
        connection.execute(
            "UPDATE meta SET value='rob2-kit.page-projection.legacy' WHERE name='page_projection'"
        )

    with pytest.raises(ValueError, match="page_projection_recipe_unsupported"):
        read_pages(workspace, "trial", str(source["id"]), [1])

    # The canonical Source identity and bytes remain untouched by the refusal.
    with _db(workspace, "canonical.sqlite3") as connection:
        stored = connection.execute(
            "SELECT value FROM meta WHERE name='page_projection'"
        ).fetchone()
    assert stored[0] == "rob2-kit.page-projection.legacy"


def test_select_text_evidence_rejects_ambiguous_normalized_matches(tmp_path: Path) -> None:
    _, source = _source_for_text(tmp_path, "target value\nother target value")

    with pytest.raises(ValueError, match="ambiguous"):
        select_text_evidence(tmp_path, "trial", str(source["id"]), 1, "target value")


def test_select_text_evidence_rejects_wrong_numeric_or_text_content(tmp_path: Path) -> None:
    _, source = _source_for_text(tmp_path, "Hazard ratio 0.61 was reported.")

    with pytest.raises(ValueError, match="not an exact page selection"):
        select_text_evidence(
            tmp_path,
            "trial",
            str(source["id"]),
            1,
            "Hazard ratio 0.62 was reported.",
        )
