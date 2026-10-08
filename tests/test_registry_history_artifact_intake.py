"""Host-captured historical views stay distinct from a current registry record."""

import hashlib
import json

import httpx
import pymupdf
import pytest

from rob2_kit.application import intake
from rob2_kit.application.evidence import list_sources, read_pages
from rob2_kit.workflow_models import TrialDeclaration


@pytest.mark.parametrize("capture_format", ["text", "rendered_pdf"])
def test_historical_capture_and_provenance_survive_current_registry_intake(
    tmp_path, monkeypatch, capture_format
):
    nct = "NCT00000001"
    current = {
        "protocolSection": {
            "identificationModule": {"nctId": nct, "officialTitle": "Example trial"}
        },
        "historical_wording": "Primary outcome",
    }
    monkeypatch.setattr(
        intake.httpx,
        "get",
        lambda *a, **k: httpx.Response(
            200, json=current, request=httpx.Request("GET", "https://clinicaltrials.gov/")
        ),
    )
    trial = tmp_path / "input" / "trial"
    trial.mkdir(parents=True)
    (trial / "sources.toml").write_text(f'nct = "{nct}"\n')
    text = f"Viewing V1 (2000-01-01)\n{nct}\nPrimary outcome\n"
    if capture_format == "text":
        name, content = "history-v1.txt", text.encode()
    else:
        with pymupdf.open() as display, pymupdf.open() as capture:
            display.new_page().insert_text((72, 72), text)
            capture.new_page().insert_image(display[0].rect, pixmap=display[0].get_pixmap())
            name, content = "history-v1.pdf", capture.tobytes()
    (trial / name).write_bytes(content)
    (trial / "sources.toml").write_text(
        f'nct = "{nct}"\n[roles]\n"{name}" = "other"\n"history-v1-provenance.json" = "other"\n'
    )
    provenance = {
        "nct": nct,
        "version_id": "1",
        "version_display_date": "2000-01-01",
        "first_submitted_date": "2000-01-01",
        "posted_date": None,
        "url": f"https://clinicaltrials.gov/study/{nct}?tab=history&a=1",
        "retrieved_at": "2026-10-08T00:00:00Z",
        "capture_format": capture_format,
        "artifact_sha256": hashlib.sha256(content).hexdigest(),
        "coverage": "Synthetic fixture only; not a provider response",
    }
    sidecar = json.dumps(provenance, indent=2).encode()
    (trial / "history-v1-provenance.json").write_bytes(sidecar)
    intake.prepare_batch(
        tmp_path,
        [TrialDeclaration(id="trial", label="trial", requested_outcome="Primary outcome")],
        expected_revision=0,
    )
    sources = list_sources(tmp_path, "trial")["sources"]
    assert len(sources) == 3
    assert len({s["id"] for s in sources}) == 3
    registry = next(s for s in sources if s["origin"] == "registry")
    assert registry["role"] == "registry"
    assert registry["media_type"] == "application/json"
    for filename, expected in [(name, content), ("history-v1-provenance.json", sidecar)]:
        source = next(s for s in sources if s["logical_path"] == filename)
        assert source["origin"] == "local_dossier"
        assert source["role"] == "other"
        assert source["media_type"] != "application/json"
        assert source["sha256"] == "sha256:" + hashlib.sha256(expected).hexdigest()
        stored = tmp_path / ".rob2-kit" / "sources" / "trial" / f"{source['id']}.bin"
        assert stored.read_bytes() == expected
    historical = next(s for s in sources if s["logical_path"] == name)
    page = read_pages(tmp_path, "trial", historical["id"], [1])["pages"][0]
    if capture_format == "text":
        assert "Viewing V1" in page["text"]
    else:
        assert historical["media_type"] == "application/pdf"
        assert not page["text"].strip()
        stored = tmp_path / ".rob2-kit" / "sources" / "trial" / f"{historical['id']}.bin"
        with pymupdf.open(stored) as pdf:
            assert pdf[0].get_images()
            assert pdf[0].get_pixmap().width > 0
    meta = next(s for s in sources if s["logical_path"] == "history-v1-provenance.json")
    projected = read_pages(tmp_path, "trial", meta["id"], [1])["pages"][0]["text"]
    assert 'version_id: "1"' in projected
    assert provenance["artifact_sha256"] in projected
    assert provenance["url"] in projected
