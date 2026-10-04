import hashlib
import socket

import httpx
import pymupdf
import pytest

from rob2_kit.application import companion_sources as companion
from rob2_kit.application._state import _state
from rob2_kit.application.evidence import list_sources, read_pages, search_sources
from rob2_kit.application.intake import prepare_batch
from rob2_kit.workflow_models import TrialDeclaration

URL = "https://journals.plos.org/document.pdf"
DOI = "10.1234/neutral"


def pdf(text="Neutral planned analysis NCT00000002"):
    with pymupdf.open() as doc:
        doc.new_page().insert_text((72, 72), text)
        return doc.tobytes()


@pytest.fixture
def network(monkeypatch):
    original = httpx.Client
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("8.8.8.8", 443))])

    def install(handler):
        monkeypatch.setattr(
            companion.httpx,
            "Client",
            lambda **k: original(transport=httpx.MockTransport(handler), **k),
        )

    return install


def reference(kind="url", locator=URL):
    return companion.CompanionReference(
        trial_id="trial",
        source_id="placeholder",
        page=1,
        citation=locator,
        linkage_rationale="Explicit reference in supplied report; applicability unknown",
        requested_role="protocol",
        locator_kind=kind,
        locator=locator,
        registry_id="NCT00000001",
    )


def test_explicit_capture_preserves_original_and_uses_normal_intake(tmp_path, network):
    network(lambda request: httpx.Response(200, content=pdf()))
    original = tmp_path / "original"
    directory = original / "input" / "trial"
    directory.mkdir(parents=True)
    (directory / "report.txt").write_text("Companion protocol reference " + URL)
    declarations = [TrialDeclaration(id="trial", label="trial", requested_outcome="neutral")]
    prepare_batch(original, declarations, 0)
    source = list_sources(original, "trial")["sources"][0]
    before = {
        str(p.relative_to(original)): p.read_bytes() for p in original.rglob("*") if p.is_file()
    }
    ref = reference().model_copy(update={"source_id": source["id"]})
    result = companion.stage_companion(original, tmp_path / "new", ref)
    assert result["capture"]["trial_relation"] == "conflicting_or_multiple_registry_identifiers"
    assert result["capture"]["parent_reference"]["sha256"] == source["sha256"]
    assert before == {
        str(p.relative_to(original)): p.read_bytes() for p in original.rglob("*") if p.is_file()
    }
    assert not (tmp_path / "new" / ".rob2-kit").exists()
    prepare_batch(tmp_path / "new", declarations, 0)
    sources = list_sources(tmp_path / "new", "trial")["sources"]
    old = next(s for s in sources if s["logical_path"] == "report.txt")
    assert old["id"] == source["id"] and old["sha256"] == source["sha256"]
    candidate = next(s for s in sources if s["logical_path"].endswith("candidate.pdf"))
    assert candidate["role"] == "other"
    assert (
        "Neutral planned"
        in read_pages(tmp_path / "new", "trial", candidate["id"], [1])["pages"][0]["text"]
    )
    assert search_sources(tmp_path / "new", "trial", "Neutral", source_id=candidate["id"])["hits"]
    assert _state(original)["revision"] == 1
    second = companion.stage_companion(original, tmp_path / "second", ref)
    assert second["candidate_path"] != result["candidate_path"]
    assert hashlib.sha256((directory / "report.txt").read_bytes()).hexdigest() in source["sha256"]
    with pytest.raises(ValueError, match="fresh workspace"):
        companion.stage_companion(original, tmp_path / "new", ref)
    with pytest.raises(ValueError, match="citation"):
        companion.stage_companion(
            original, tmp_path / "bad", ref.model_copy(update={"citation": "invented"})
        )


@pytest.mark.parametrize(
    "links,status,reason",
    [
        ([{"URL": URL, "content-type": "application/pdf"}], "captured", None),
        ([], "unresolved", "no_unique_supported_authoritative_pdf_link"),
        (
            [
                {"URL": URL, "content-type": "application/pdf"},
                {"URL": URL + "?v=2", "content-type": "application/pdf"},
            ],
            "unresolved",
            "no_unique_supported_authoritative_pdf_link",
        ),
    ],
)
def test_doi_metadata_links_are_exact_and_bounded(network, links, status, reason):
    network(
        lambda request: (
            httpx.Response(200, json={"message": {"DOI": DOI, "link": links}})
            if request.url.host == "api.crossref.org"
            else httpx.Response(200, content=pdf("No registry identifier"))
        )
    )
    content, report = companion._acquire(reference("doi", DOI))
    assert report["status"] == status
    assert report.get("reason") == reason
    assert report["metadata_sha256"] and report["trial_relation"] == "unverified"
    assert (content is not None) == (status == "captured")


def test_mismatched_doi_metadata_does_not_fetch_document(network):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(
            200,
            json={
                "message": {
                    "DOI": "10.1234/different",
                    "link": [{"URL": URL, "content-type": "application/pdf"}],
                }
            },
        )

    network(handler)
    assert (
        companion._acquire(reference("doi", DOI))[1]["reason"] == "doi_metadata_identity_mismatch"
    )
    assert len(calls) == 1


@pytest.mark.parametrize(
    "target",
    [
        "file:///tmp/private",
        "http://journals.plos.org/file",
        "https://127.0.0.1/file",
        "https://user:secret@journals.plos.org/file",
        "https://169.254.169.254/file",
        "https://unvetted.example/file",
    ],
)
def test_forbidden_redirect_never_requested(network, target):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={"location": target})

    network(handler)
    content, report = companion._acquire(reference())
    assert content is None and report["status"] == "unresolved" and calls == [URL]


def test_public_redirect_and_private_dns(network, monkeypatch):
    network(
        lambda request: (
            httpx.Response(302, headers={"location": "/final.pdf"})
            if str(request.url) == URL
            else httpx.Response(200, content=pdf())
        )
    )
    assert companion._acquire(reference())[1]["redirect_chain"] == [
        URL,
        "https://journals.plos.org/final.pdf",
    ]
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("127.0.0.1", 443))])
    assert companion._acquire(reference())[1]["reason"] == "nonpublic_destination"


@pytest.mark.parametrize(
    "status,content", [(200, b"<html>paywall</html>"), (404, b"missing"), (200, b"%PDF-invalid")]
)
def test_failed_access_and_nonpdf_are_unresolved(network, status, content):
    network(lambda request: httpx.Response(status, content=content))
    assert companion._acquire(reference())[0] is None


def test_timeout_and_size_limit_are_unresolved(network, monkeypatch):
    def timeout(request):
        raise httpx.ReadTimeout("public access timed out", request=request)

    network(timeout)
    assert companion._acquire(reference())[1]["reason"] == "ReadTimeout"
    network(lambda request: httpx.Response(200, content=pdf()))
    monkeypatch.setattr(companion, "MAX_BYTES", 10)
    assert companion._acquire(reference())[1]["reason"] == "document_size_limit"


def test_observed_matching_identifier_is_still_not_applicability(network):
    network(lambda request: httpx.Response(200, content=pdf("Plan NCT00000001")))
    _, report = companion._acquire(reference())
    assert report["trial_relation"] == "registry_identifier_observed"
    assert report["source_role"] == "other"
    assert any("do not establish applicability" in warning for warning in report["limitations"])


def test_compressed_response_is_unresolved(network):
    network(
        lambda request: httpx.Response(
            200, stream=httpx.ByteStream(pdf()), headers={"content-encoding": "br"}
        )
    )
    assert companion._acquire(reference())[1]["reason"] == "unsupported_content_encoding"
