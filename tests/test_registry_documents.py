"""Official document capture is new evidence, never a scientific judgment."""

import hashlib
import json
import runpy
import socket
from pathlib import Path

import httpx
import pymupdf
import pytest

from rob2_kit.application import intake
from rob2_kit.application._state import _state
from rob2_kit.application.evidence import list_sources, read_pages, search_sources
from rob2_kit.application.finalization import _valid_batch
from rob2_kit.application.registry_documents import acquire_documents
from rob2_kit.workflow_models import TrialDeclaration


def _mock_http(monkeypatch, get):
    original = httpx.Client
    monkeypatch.setattr(intake.httpx, "get", get)
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("8.8.8.8", 443))])

    def handler(request):
        return get(str(request.url), follow_redirects=False, timeout=20)

    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs)
    )


def _record(nct, docs):
    return json.dumps(
        {
            "protocolSection": {
                "identificationModule": {"nctId": nct, "officialTitle": "Unrelated fixture study"}
            },
            "documentSection": {"largeDocumentModule": {"largeDocs": docs}},
        }
    ).encode()


def _pdf():
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        page.insert_text((72, 72), "Planned analysis of the primary outcome.")
        return pdf.tobytes()


@pytest.mark.parametrize(
    "nct,rows,roles",
    [
        (
            "NCT00000001",
            [
                {
                    "filename": "Prot_SAP_000.pdf",
                    "typeAbbrev": "Prot_SAP",
                    "hasProtocol": True,
                    "hasSap": True,
                    "date": "2018-01-01",
                    "uploadDate": "2020-02-02",
                }
            ],
            ["protocol"],
        ),
        (
            "NCT00000002",
            [
                {"filename": "Prot_000.pdf", "hasProtocol": True, "hasSap": False},
                {"filename": "SAP_001.pdf", "typeAbbrev": "SAP"},
            ],
            ["protocol", "sap"],
        ),
    ],
)
def test_combined_and_separate_official_document_structures(monkeypatch, nct, rows, roles):
    content = _pdf()
    urls = []

    def get(url, **kwargs):
        urls.append(url)
        assert kwargs["follow_redirects"] is False
        return httpx.Response(200, content=content, request=httpx.Request("GET", url))

    _mock_http(monkeypatch, get)
    documents, report = acquire_documents(nct, _record(nct, rows))
    assert [doc.role for doc in documents] == roles
    assert all(
        url.startswith(f"https://cdn.clinicaltrials.gov/large-docs/{nct[-2:]}/{nct}/")
        for url in urls
    )
    assert report["status"] == "captured"
    for entry in report["documents"]:
        assert entry["sha256"] == "sha256:" + hashlib.sha256(content).hexdigest()
        assert entry["retrieved_at"]
    assert report["capture_kind"] == "new_public_capture_not_historical_replay"
    assert report["limitations"]


@pytest.mark.parametrize(
    "nct,rows,status",
    [
        (
            "NCT00000002",
            [{"filename": "Prot_000.pdf", "typeAbbrev": "Prot"}],
            "trial_linkage_mismatch",
        ),
        ("NCT00000001", [], "no_linked_documents_in_current_record"),
        (
            "NCT00000001",
            [{"filename": "../Prot.pdf", "typeAbbrev": "Prot"}],
            "no_documents_captured",
        ),
        (
            "NCT00000001",
            [
                {"filename": "Prot_000.pdf", "typeAbbrev": "Prot"},
                {"filename": "Prot_000.pdf", "typeAbbrev": "SAP"},
            ],
            "no_documents_captured",
        ),
        (
            "NCT00000001",
            [{"filename": "Prot_000.pdf", "typeAbbrev": "Prot", "hasProtocol": False}],
            "no_documents_captured",
        ),
    ],
)
def test_missing_ambiguous_mismatched_links_do_not_fetch(monkeypatch, nct, rows, status):
    monkeypatch.setattr(
        intake.httpx, "get", lambda *a, **k: pytest.fail("unsafe or ambiguous link fetched")
    )
    documents, report = acquire_documents(nct, _record("NCT00000001", rows))
    assert not documents and report["status"] == status


@pytest.mark.parametrize("response", [b"<html>Unavailable</html>", b"%PDF-invalid"])
def test_failed_or_invalid_pdf_fetch_is_an_explicit_unknown(monkeypatch, response):
    _mock_http(
        monkeypatch,
        lambda url, **k: httpx.Response(200, content=response, request=httpx.Request("GET", url)),
    )
    documents, report = acquire_documents(
        "NCT00000001", _record("NCT00000001", [{"filename": "SAP_000.pdf", "typeAbbrev": "SAP"}])
    )
    assert not documents
    assert report["documents"][0]["status"] == "fetch_unavailable"


def test_acquisition_enters_inventory_search_reading_and_both_batch_verifiers(
    tmp_path, monkeypatch
):
    nct = "NCT00000001"
    record = _record(nct, [{"filename": "SAP_000.pdf", "typeAbbrev": "SAP", "date": "2020-01-01"}])
    content = _pdf()

    def get(url, **kwargs):
        return httpx.Response(
            200, content=record if "/api/" in url else content, request=httpx.Request("GET", url)
        )

    _mock_http(monkeypatch, get)
    trial = tmp_path / "input" / "trial"
    trial.mkdir(parents=True)
    (trial / "main.txt").write_text("Study report NCT00000001")
    (trial / "sources.toml").write_text(
        '[registry]\nnct = "NCT00000001"\nacquire_documents = true\n'
    )
    result = intake.prepare_batch(
        tmp_path, [TrialDeclaration(id="trial", label="trial", requested_outcome="outcome")], 0
    )
    assert result["outcome"] == "success"
    batch = _state(tmp_path)["batch"]
    assert _valid_batch(batch)
    standalone = runpy.run_path(
        str(Path(__file__).resolve().parents[1] / "scripts" / "verify_bundle.py")
    )
    assert standalone["_valid_batch"](batch)
    sources = list_sources(tmp_path, "trial")["sources"]
    sap = next(s for s in sources if s["role"] == "sap")
    assert sap["origin"] == "registry" and "registry_documents/" in sap["logical_path"]
    assert sap["sha256"] == "sha256:" + hashlib.sha256(content).hexdigest()
    assert "Planned analysis" in read_pages(tmp_path, "trial", sap["id"], [1])["pages"][0]["text"]
    assert any(
        hit["source_id"] == sap["id"]
        for hit in search_sources(tmp_path, "trial", "Planned analysis")["hits"]
    )
    metadata = next(s for s in sources if s["logical_path"].endswith("/capture.json"))
    assert (
        "new_public_capture_not_historical_replay"
        in read_pages(tmp_path, "trial", metadata["id"], [1])["pages"][0]["text"]
    )
    monkeypatch.setattr(
        intake.httpx, "get", lambda *a, **k: pytest.fail("existing capture refreshed")
    )
    assert (
        intake.prepare_batch(
            tmp_path, [TrialDeclaration(id="trial", label="trial", requested_outcome="outcome")], 0
        )["retry"]
        is True
    )


def test_nonplanning_metadata_is_distinct_from_missing_or_ambiguous_links(monkeypatch):
    monkeypatch.setattr(
        intake.httpx, "get", lambda *a, **k: pytest.fail("nonplanning file fetched")
    )
    documents, report = acquire_documents(
        "NCT00000001",
        _record(
            "NCT00000001",
            [
                {
                    "filename": "ICF_000.pdf",
                    "typeAbbrev": "ICF",
                    "hasIcf": True,
                    "hasProtocol": False,
                    "hasSap": False,
                }
            ],
        ),
    )
    assert not documents
    assert report["documents"][0]["status"] == "metadata_not_marked_protocol_or_sap"


def test_official_document_redirect_is_not_followed(monkeypatch):
    calls = []

    def get(url, **kwargs):
        calls.append(url)
        assert kwargs["follow_redirects"] is False
        return httpx.Response(
            302, headers={"Location": "http://127.0.0.1/private"}, request=httpx.Request("GET", url)
        )

    _mock_http(monkeypatch, get)
    documents, report = acquire_documents(
        "NCT00000001",
        _record(
            "NCT00000001",
            [
                {
                    "filename": "SAP_000.pdf",
                    "typeAbbrev": "SAP",
                    "url": "file:///private/document.pdf",
                }
            ],
        ),
    )
    assert len(calls) == 1
    assert calls[0] == "https://cdn.clinicaltrials.gov/large-docs/01/NCT00000001/SAP_000.pdf"
    assert not documents and report["documents"][0]["status"] == "fetch_unavailable"


@pytest.mark.parametrize("failure", ["size", "encoding", "private_dns"])
def test_registry_pdf_shares_bounded_no_proxy_transport(monkeypatch, failure):
    from rob2_kit.application import registry_documents

    original = httpx.Client
    calls = []

    def handler(request):
        calls.append(str(request.url))
        assert request.headers["accept-encoding"] == "identity"
        return httpx.Response(
            200,
            stream=httpx.ByteStream(_pdf()),
            headers={"content-encoding": "br"} if failure == "encoding" else {},
        )

    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return original(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "Client", client)
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [
            (2, 1, 6, "", ("127.0.0.1" if failure == "private_dns" else "8.8.8.8", 443))
        ],
    )
    if failure == "size":
        monkeypatch.setattr(registry_documents, "MAX_DOCUMENT_BYTES", 10)
    documents, report = acquire_documents(
        "NCT00000001", _record("NCT00000001", [{"filename": "Prot_000.pdf", "typeAbbrev": "Prot"}])
    )
    assert not documents and report["documents"][0]["status"] == "fetch_unavailable"
    assert report["document_transport"]["environment_proxies"] is False
    assert len(calls) == (0 if failure == "private_dns" else 1)
