from __future__ import annotations

import hashlib
import io
import json
from types import SimpleNamespace

import pytest
from PIL import Image

from rob2_kit.application.run_engine import RunEngine, VisualAssetMaterializationError
from rob2_kit.domain.canonical import canonical_hash, sha256_digest
from rob2_kit.evidence import (
    CanonicalEvidenceUnit,
    CanonicalUnitKind,
    CanonicalWordBox,
    build_visual_citation,
)
from rob2_kit.evidence.search import EvidenceSearchIndex
from rob2_kit.ingestion.project import PageRender
from rob2_kit.reports import VisualCitationView

HASH = "sha256:" + "a" * 64


def test_visual_citation_uses_word_geometry_and_marks_block_fallback() -> None:
    unit = CanonicalEvidenceUnit(
        unit_id="unit:report-p1-b1",
        source_id="source:report",
        source_artifact_hash=HASH,
        parse_id="parse:report-1",
        page=1,
        kind=CanonicalUnitKind.PARAGRAPH,
        text="Allocation was concealed.",
        spatial=(10.0, 20.0, 200.0, 60.0),
        word_boxes=(
            CanonicalWordBox(
                text="Allocation", span_start=0, span_end=10, spatial=(10, 20, 80, 30)
            ),
            CanonicalWordBox(
                text="was", span_start=11, span_end=14, spatial=(84, 20, 105, 30)
            ),
            CanonicalWordBox(
                text="concealed", span_start=15, span_end=24, spatial=(109, 20, 170, 30)
            ),
        ),
    )

    exact = build_visual_citation(unit, span_start=0, span_end=10)
    block = build_visual_citation(unit, span_start=1, span_end=10)

    assert exact.geometry_scope == "phrase_exact"
    assert exact.boxes[0].model_dump(mode="json") == {
        "left": 10.0,
        "top": 20.0,
        "right": 80.0,
        "bottom": 30.0,
    }
    assert block.geometry_scope == "block"
    assert block.boxes == (
        type(block.boxes[0])(left=10, top=20, right=200, bottom=60),
    )
    assert exact.geometry_hash != block.geometry_hash


def test_search_index_round_trip_retains_word_geometry(tmp_path) -> None:
    unit = CanonicalEvidenceUnit(
        unit_id="unit:report-p1-b1",
        source_id="source:report",
        source_artifact_hash=HASH,
        parse_id="parse:report-1",
        page=1,
        kind=CanonicalUnitKind.PARAGRAPH,
        text="Allocation",
        spatial=(10.0, 20.0, 200.0, 60.0),
        word_boxes=(
            CanonicalWordBox(
                text="Allocation", span_start=0, span_end=10, spatial=(10, 20, 80, 30)
            ),
        ),
    )
    index = EvidenceSearchIndex(tmp_path / "evidence.sqlite3")
    index.replace_units((unit,))
    assert index.read_unit(unit.unit_id).word_boxes == unit.word_boxes


def test_visual_citation_view_serializes_machine_verifiable_identity() -> None:
    view = VisualCitationView(
        citation_id="visual:1",
        canonical_unit_id="unit:report-p1-b1",
        source_id="source:report",
        source_artifact_hash=HASH,
        parse_id="parse:report-1",
        page=1,
        region=(10.0, 20.0, 80.0, 30.0),
        boxes=((10.0, 20.0, 80.0, 30.0),),
        label="Canonical evidence span",
        exact_phrase="Allocation",
        span_start=0,
        span_end=10,
        quoted_text_hash=sha256_digest(b"Allocation"),
        geometry_scope="phrase_exact",
        geometry_hash=canonical_hash({"box": [10, 20, 80, 30]}),
        render_hash=canonical_hash({"page": 1, "dpi": 144}),
        render_mode="crop",
        dpi=144,
        base_render_hash=HASH,
        derived_render_hash=HASH,
        overlay_hash=HASH,
        crop_hash=HASH,
        context_hash=HASH,
        crop_path="visual-assets/a-crop.png",
        context_path="visual-assets/a-page.png",
        agent_inspected=False,
        inspection_status="automatic_spatial_claim",
    )

    payload = view.model_dump(mode="json", exclude_none=True)
    for field in (
        "source_artifact_hash",
        "parse_id",
        "span_start",
        "span_end",
        "quoted_text_hash",
        "geometry_hash",
        "render_hash",
        "base_render_hash",
        "derived_render_hash",
        "overlay_hash",
        "crop_hash",
        "context_hash",
        "agent_inspected",
    ):
        assert field in payload


def _asset_engine(*, parser: object) -> tuple[RunEngine, object, VisualCitationView]:
    image = Image.new("RGB", (100, 60), "white")
    raw = io.BytesIO()
    image.save(raw, format="PNG")
    engine = RunEngine(parser=parser)
    engine._result_spec_for = lambda *_args: SimpleNamespace(
        result=SimpleNamespace(trial_id="trial:1")
    )
    engine._latest_prepared_record = lambda _ledger: SimpleNamespace(
        proposal=SimpleNamespace(
            initialization=SimpleNamespace(
                trials=(
                    SimpleNamespace(
                        trial_id="trial:1",
                        inventory=SimpleNamespace(
                            sources=(
                                SimpleNamespace(
                                    source_id="source:1", artifact_hash=HASH
                                ),
                            )
                        ),
                    ),
                )
            )
        )
    )
    citation = VisualCitationView(
        citation_id="visual:asset",
        source_id="source:1",
        source_artifact_hash=HASH,
        page=2,
        region=(2.0, 3.0, 20.0, 12.0),
        boxes=((2.0, 3.0, 20.0, 12.0),),
        label="Primary table",
        agent_inspected=False,
        inspection_status="automatic_spatial_claim",
    )
    ledger = SimpleNamespace(artifacts=SimpleNamespace(read=lambda _digest: b"source"))
    return engine, ledger, citation


def test_visual_assets_record_hashes_and_fail_closed() -> None:
    image = Image.new("RGB", (100, 60), "white")
    raw = io.BytesIO()
    image.save(raw, format="PNG")

    class Parser:
        def screenshot(self, _data: bytes, *, page_numbers: tuple[int, ...], dpi: int):
            return (
                PageRender(
                    page_number=2,
                    dpi=dpi,
                    pixel_width=100,
                    pixel_height=60,
                    image_hash=HASH,
                    image_bytes=raw.getvalue(),
                ),
            )

    engine, ledger, citation = _asset_engine(parser=Parser())
    views, assets = engine._materialize_visual_assets(ledger, "run:1", "result:1", (citation,))
    rendered = views[0]
    assert rendered.crop_path and rendered.context_path
    assert rendered.base_render_hash == HASH
    assert rendered.crop_hash == sha256_digest(assets[rendered.crop_path])
    assert rendered.context_hash == sha256_digest(assets[rendered.context_path])
    assert rendered.overlay_hash == rendered.context_hash

    class BrokenParser:
        def screenshot(self, *_args, **_kwargs):
            raise OSError("render unavailable")

    broken_engine, broken_ledger, broken_citation = _asset_engine(parser=BrokenParser())
    with pytest.raises(VisualAssetMaterializationError, match="render failed"):
        broken_engine._materialize_visual_assets(
            broken_ledger, "run:1", "result:1", (broken_citation,)
        )


def test_visual_asset_hashes_are_manifest_bound(tmp_path) -> None:
    files = {
        "visual-citations.json": b'{"visual_citations":[]}',
        "visual-assets/crop.png": b"crop",
        "visual-assets/page.png": b"page",
    }
    manifest = {
        "files": {
            name: "sha256:" + hashlib.sha256(content).hexdigest()
            for name, content in files.items()
        }
    }
    files["manifest.json"] = (
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    )
    for name, content in files.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    RunEngine._verify_staged_report_files(tmp_path, files)
    (tmp_path / "visual-assets/page.png").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="failed verification"):
        RunEngine._verify_staged_report_files(tmp_path, files)
