"""Fail-closed independent verifier for serialized finalization bundles."""
# ruff: noqa: E501, E701, E741

from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

import pymupdf

from rob2_kit.packs import MAINTAINER_POLICY_PACK, SCIENTIFIC_PACK

from .manifest import ObjectiveFactManifest, check_reported_facts


def _presentation(counts: dict[str, Any]) -> dict[str, str] | None:
    """Derive the public wording here, rather than trusting the producer."""
    try:
        total = int(counts["total"])
        assessed = int(counts["assessed"])
        needs_input = int(counts["needs_input"])
        failed = int(counts["failed"])
        pending = int(counts["pending"])
    except (KeyError, TypeError, ValueError):
        return None
    if min(total, assessed, needs_input, failed, pending) < 0 or pending:
        return None
    assessment = "assessment" if assessed == 1 else "assessments"
    trial = "Trial" if assessed == 1 else "Trials"
    if assessed == total and assessed > 0:
        return {
            "code": "finalized_all_assessed",
            "headline": f"{assessed} RoB 2 {assessment} completed",
            "summary": f"Batch finalized. RoB 2 {assessment} completed for {assessed} {trial}.",
        }
    if assessed == 0:
        details: list[str] = []
        if needs_input:
            details.append(
                f"{needs_input} {'Trial needs' if needs_input == 1 else 'Trials need'} researcher input."
            )
        if failed:
            details.append(f"{failed} {'Trial failed' if failed == 1 else 'Trials failed'}.")
        return {
            "code": "finalized_zero_assessed",
            "headline": "Batch finalized",
            "summary": "Batch finalized. No RoB 2 assessments were completed."
            + (" " + " ".join(details) if details else ""),
        }
    return {
        "code": "finalized_mixed",
        "headline": f"{assessed} RoB 2 {assessment} completed",
        "summary": (
            f"Batch finalized. RoB 2 {assessment} completed for {assessed} {trial}; "
            f"{needs_input} {'Trial needs' if needs_input == 1 else 'Trials need'} researcher input "
            f"and {failed} {'Trial failed' if failed == 1 else 'Trials failed'}."
        ),
    }


def _canonical(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + sha256(encoded.encode()).hexdigest()


def _bytes_hash(value: bytes) -> str:
    return "sha256:" + sha256(value).hexdigest()


def _ref(value: object, kind: str | None = None) -> str | None:
    if not isinstance(value, dict) or not isinstance(value.get("identity"), str):
        return None
    if kind is not None and value.get("kind") != kind:
        return None
    identity, uri = value["identity"], value.get("uri")
    if not identity.startswith("sha256:") or not isinstance(uri, str) or not uri.endswith(identity):
        return None
    return identity


def _ref_record(kind: str, identity: object) -> dict[str, str] | None:
    if not isinstance(identity, str):
        return None
    return {"kind": kind, "identity": identity, "uri": f"rob2://detail/{kind}/{identity}"}


def _evidence_ref(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    identity = value.get("identity")
    return identity if isinstance(identity, str) and identity.startswith("sha256:") else None


@dataclass(frozen=True)
class VerificationResult:
    ok: bool
    failures: tuple[str, ...]
    facts_checked: tuple[str, ...]


class _Bundle:
    def __init__(self, root: Path, failures: list[str]):
        self.root, self.failures = root, failures
        self.records: dict[str, dict[str, Any]] = {}
        self.names: dict[str, dict[str, Any]] = {}

    def load(self) -> None:
        try:
            manifest = json.loads((self.root / "manifest.json").read_text(encoding="utf-8"))
            rows = manifest["files"]
            base = {"summary_hash": manifest["summary_hash"], "files": rows}
            if not isinstance(rows, list) or _canonical(base) != manifest.get("manifest_hash"):
                raise ValueError
            listed: set[str] = set()
            for row in rows:
                relative = row.get("path") if isinstance(row, dict) else None
                if not isinstance(relative, str) or not isinstance(row.get("sha256"), str):
                    raise ValueError
                path = self.root / relative
                if ".." in Path(relative).parts or path.is_symlink() or not path.is_file():
                    raise ValueError
                if _bytes_hash(path.read_bytes()) != row["sha256"] or relative in listed:
                    raise ValueError
                listed.add(relative)
            actual = {
                p.relative_to(self.root).as_posix() for p in self.root.rglob("*") if p.is_file()
            }
            if actual != listed | {"manifest.json"}:
                raise ValueError
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            self.failures.append("artifact manifest, inventory, or file hash is invalid")
            return
        records = self.root / "records"
        for path in records.rglob("*.json") if records.is_dir() else ():
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                self.failures.append("record JSON is corrupt")
                continue
            if not isinstance(record, dict):
                self.failures.append("record is not an object")
                continue
            self.names[path.name] = record
            identity = record.get("identity")
            if isinstance(identity, str):
                if identity in self.records:
                    self.failures.append("duplicate canonical record identity")
                self.records[identity] = record


def _domain_oracle(candidate: dict[str, Any]) -> str | None:
    """Independent RoB 2 rules for the canonical answer vocabulary."""
    draft = candidate.get("draft")
    rows = draft.get("active_answers") if isinstance(draft, dict) else None
    if not isinstance(rows, list):
        return None
    answers = {row.get("question_id"): row.get("answer") for row in rows if isinstance(row, dict)}
    yes, no = {"yes", "probably_yes"}, {"no", "probably_no"}
    no_u = no | {"no_information"}
    domain = candidate.get("domain_id")
    if domain == "domain:randomization":
        c, b = (
            answers.get("sq:randomization:concealment"),
            answers.get("sq:randomization:baseline-imbalance"),
        )
        if c in no or (c == "no_information" and b in yes):
            return "high"
        return (
            "some_concerns"
            if answers.get("sq:randomization:sequence") in no or c == "no_information" or b in yes
            else "low"
        )
    if domain == "domain:missing":
        a, u, d, l = (
            answers.get(f"sq:missing:{key}")
            for key in (
                "data-available",
                "evidence-unbiased",
                "true-value-dependent",
                "likely-dependent",
            )
        )
        if a in yes or u in yes or d in no:
            return "low"
        return "high" if l in yes | {"no_information"} else "some_concerns"
    if domain == "domain:measurement":
        i, d, l = (
            answers.get(f"sq:measurement:{key}")
            for key in ("method-inappropriate", "differential", "influence-likely")
        )
        if i in yes or d in yes or l in yes | {"no_information"}:
            return "high"
        return "some_concerns" if d == "no_information" or l in no else "low"
    if domain == "domain:selection":
        m, a = (
            answers.get("sq:selection:multiple-measurements"),
            answers.get("sq:selection:multiple-analyses"),
        )
        if m in yes or a in yes:
            return "high"
        return (
            "some_concerns"
            if answers.get("sq:selection:prespecified-analysis") in no_u
            or m == "no_information"
            or a == "no_information"
            else "low"
        )
    if domain == "domain:deviations":
        c, a, b = (
            answers.get(f"sq:deviations:{key}")
            for key in ("context-deviations", "affected-outcome", "balanced")
        )
        p, i = (
            answers.get("sq:deviations:appropriate-analysis"),
            answers.get("sq:deviations:substantial-impact"),
        )
        if c in yes and a in yes | {"no_information"} and b in no_u:
            return "high"
        if p in no_u and i in yes | {"no_information"}:
            return "high"
        return "some_concerns" if c == "no_information" or a in no or b in yes or i in no else "low"
    return None


def _overall_judgment(judgments: list[str]) -> str:
    if "high" in judgments:
        return "high"
    if "some_concerns" in judgments:
        return "some_concerns"
    return "low"


def _summary(bundle: _Bundle) -> dict[str, Any] | None:
    try:
        value = json.loads((bundle.root / "summary.json").read_text(encoding="utf-8"))
        payload = {
            key: value[key] for key in ("approved_batch", "counts", "trials", "presentation")
        }
        if value.get("kind") != "finalization" or _canonical(payload) != value.get("identity"):
            raise ValueError
        if _ref(value["approved_batch"], "approved_batch") is None:
            raise ValueError
        counts, trials = value["counts"], value["trials"]
        actual = {
            key: sum(row.get("disposition") == key for row in trials)
            for key in ("assessed", "needs_input", "failed")
        }
        if counts != {"total": len(trials), "pending": 0, **actual}:
            raise ValueError
        if value.get("presentation") != _presentation(counts):
            raise ValueError
        return value
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        bundle.failures.append("finalization summary identity, counts, or references are invalid")
        return None


def _proposal(bundle: _Bundle, key: str, objective: ObjectiveFactManifest) -> dict[str, Any] | None:
    value = bundle.names.get("proposal_review.json")
    if value is None:
        bundle.failures.append("durable Proposal review is unavailable")
        return None
    base = {
        field: value.get(field)
        for field in ("captured_batch", "outcome_statement", "results", "needs_input")
    }
    if value.get("kind") != "proposal_review" or _canonical(base) != value.get("identity"):
        bundle.failures.append("Proposal identity is invalid")
        return None
    if _ref(value.get("captured_batch"), "captured_batch") is None:
        bundle.failures.append("Proposal does not bind a captured Batch")
    facts = objective.outcome(key)
    selected = value.get("results")
    if not isinstance(selected, list) or len(selected) != 1:
        bundle.failures.append("Proposal has no exact Result card for the release outcome")
    else:
        bundle.failures.extend(check_reported_facts(facts, selected[0]))
    if facts.expected_terminal == "needs_input":
        needs = value.get("needs_input")
        if not isinstance(needs, list) or len(needs) != 1:
            bundle.failures.append("adverse events requires a separate needs-input disposition")
        elif needs[0].get("reason") != "comparator_unavailable":
            bundle.failures.append("adverse-events needs-input reason must be missing comparator")
    return value


def _sources_and_evidence(bundle: _Bundle, proposal: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Bind captured source bytes and every retained Evidence record independently."""
    captured = bundle.names.get("captured_batch.json")
    if captured is None:
        bundle.failures.append("captured Batch is unavailable")
        return {}
    payload = {key: captured.get(key) for key in ("plan", "acknowledgment", "sources")}
    if captured.get("kind") != "captured_batch" or _canonical(payload) != captured.get("identity"):
        bundle.failures.append("captured Batch identity is invalid")
        return {}
    plan_value = captured.get("plan")
    plan_id = (
        plan_value
        if isinstance(plan_value, str) and plan_value.startswith("sha256:")
        else _ref(plan_value, "intake_plan")
    )
    plan = bundle.names.get("intake_plan.json")
    ack_value = captured.get("acknowledgment")
    intake_ack_id = (
        ack_value
        if isinstance(ack_value, str) and ack_value.startswith("sha256:")
        else _ref(ack_value, "review_ack")
    )
    intake_ack = bundle.names.get("review_ack.json")
    plan_payload = (
        {key: plan.get(key) for key in ("preflight", "entries", "blockers", "conditions")}
        if plan is not None
        else None
    )
    ack_payload = (
        {
            key: intake_ack.get(key)
            for key in ("record", "authority", "purpose", "caller", "observed_at")
        }
        if intake_ack is not None
        else None
    )
    conditional_intake = bool((plan or {}).get("conditions"))
    expected_intake_authority = "researcher" if conditional_intake else "host"
    valid_intake_caller = (
        str((intake_ack or {}).get("caller", "")).startswith(("cli:", "server:"))
        if conditional_intake
        else str((intake_ack or {}).get("caller", "")).startswith("host:")
    )
    if (
        plan is None
        or plan.get("kind") != "intake_plan"
        or plan.get("identity") != plan_id
        or _canonical(plan_payload) != plan_id
        or intake_ack is None
        or intake_ack.get("kind") != "review_ack"
        or intake_ack.get("identity") != intake_ack_id
        or _canonical(ack_payload) != intake_ack_id
        or intake_ack.get("record") != _ref_record("intake_plan", plan_id)
        or intake_ack.get("purpose") != "intake"
        or intake_ack.get("authority") != expected_intake_authority
        or not valid_intake_caller
    ):
        bundle.failures.append("captured Intake plan and acknowledgment chain is invalid")
    if _ref(proposal.get("captured_batch"), "captured_batch") != captured.get("identity"):
        bundle.failures.append("Proposal does not bind the exact captured Batch")
    sources: dict[str, tuple[str, bytes, tuple[str, ...], str]] = {}
    for source in captured.get("sources", []):
        if not isinstance(source, dict):
            bundle.failures.append("captured Source record is invalid")
            continue
        source_id, trial, source_hash, recorded_media_type = (
            source.get("candidate_identity"),
            source.get("trial_id"),
            source.get("sha256"),
            source.get("media_type"),
        )
        path = bundle.root / "sources" / str(trial) / str(source_id)
        if (
            not isinstance(source_id, str)
            or not isinstance(trial, str)
            or not isinstance(source_hash, str)
        ):
            bundle.failures.append("captured Source identity is invalid")
        elif not path.is_file() or _bytes_hash(path.read_bytes()) != source_hash:
            bundle.failures.append("captured Source bytes are unavailable or corrupt")
        else:
            data = path.read_bytes()
            media_type = recorded_media_type or (
                "application/pdf" if data.startswith(b"%PDF-") else "text/plain"
            )
            try:
                if media_type == "application/pdf" or data.startswith(b"%PDF-"):
                    document = pymupdf.open(stream=data, filetype="pdf")
                    try:
                        pages = tuple(page.get_text() for page in document)
                    finally:
                        document.close()
                else:
                    pages = (data.decode("utf-8"),)
            except (UnicodeDecodeError, ValueError, pymupdf.FileDataError):
                pages = ()
            page_hashes = tuple(_bytes_hash(page.encode()) for page in pages)
            projection_hash = _canonical(
                {
                    "recipe": "rob2-kit.extract-pages.v1",
                    "source_sha256": source_hash,
                    "media_type": media_type,
                    "page_hashes": page_hashes,
                }
            )
            sources[source_id] = (trial, data, pages, projection_hash)
    evidence: dict[str, dict[str, Any]] = {}
    for row in bundle.records.values():
        if row.get("kind") == "visual":
            _validate_visual_evidence(bundle, sources, row, evidence)
            continue
        if row.get("kind") != "text":
            continue
        fields = (
            "kind",
            "trial_id",
            "snapshot",
            "source_id",
            "source_sha256",
            "projection_hash",
            "page",
            "start",
            "end",
            "quote",
            "quote_sha256",
        )
        if _canonical({key: row.get(key) for key in fields}) != row.get("identity"):
            bundle.failures.append("Evidence identity is invalid")
            continue
        source = sources.get(row.get("source_id"))
        quote = row.get("quote")
        page = row.get("page")
        source_page = (
            source[2][page - 1]
            if source is not None and isinstance(page, int) and 1 <= page <= len(source[2])
            else None
        )
        if (
            source is None
            or row.get("trial_id") != source[0]
            or row.get("source_sha256") != _bytes_hash(source[1])
            or row.get("projection_hash") != source[3]
            or not isinstance(quote, str)
            or row.get("quote_sha256") != _bytes_hash(quote.encode())
            or not isinstance(row.get("start"), int)
            or not isinstance(row.get("end"), int)
            or source_page is None
            or source_page[row["start"] : row["end"]] != quote
        ):
            bundle.failures.append("Evidence provenance or exact quote binding is invalid")
        else:
            evidence[str(row.get("identity"))] = row
    return evidence


def _validate_visual_evidence(
    bundle: _Bundle,
    sources: dict[str, tuple[str, bytes, tuple[str, ...], str]],
    row: dict[str, Any],
    evidence: dict[str, dict[str, Any]],
) -> None:
    fields = (
        "kind", "trial_id", "snapshot", "source_id", "source_sha256", "projection_hash",
        "page", "region", "render", "transcription",
    )
    if _canonical({key: row.get(key) for key in fields}) != row.get("identity"):
        bundle.failures.append("visual Evidence identity is invalid")
        return
    source = sources.get(row.get("source_id"))
    page = row.get("page")
    region = row.get("region")
    render = row.get("render")
    render_id = render.get("identity") if isinstance(render, dict) else None
    if (
        source is None
        or row.get("trial_id") != source[0]
        or row.get("source_sha256") != _bytes_hash(source[1])
        or row.get("projection_hash") != source[3]
        or not isinstance(page, int)
        or not 1 <= page <= len(source[2])
        or not isinstance(row.get("snapshot"), str)
        or not isinstance(row.get("transcription"), str)
        or not row["transcription"].strip()
        or not isinstance(render, dict)
        or not isinstance(render_id, str)
        or not isinstance(render.get("uri"), str)
        or render["uri"] != f"rob2://render/{render_id}"
        or not _valid_region(region)
        or row.get("snapshot") != _captured_snapshot(bundle, sources, row.get("trial_id"))
    ):
        bundle.failures.append("visual Evidence provenance is invalid")
        return
    token = render_id.removeprefix("sha256:")
    image_path = bundle.root / "renders" / f"{token}.png"
    try:
        metadata = bundle.names[f"render-{token}.json"]
        image = image_path.read_bytes()
    except (KeyError, OSError):
        bundle.failures.append("visual Evidence render record or PNG is unavailable")
        return
    render_payload = {
        "source_id": metadata.get("source_id"), "source_sha256": metadata.get("source_hash"),
        "page": metadata.get("page_number"), "region": metadata.get("region"),
        "recipe": metadata.get("recipe"), "width": metadata.get("width"),
        "height": metadata.get("height"), "pixel_width": metadata.get("pixel_width"),
        "pixel_height": metadata.get("pixel_height"), "media_type": metadata.get("media_type"),
        "png_sha256": metadata.get("sha256"),
    }
    if (
        _canonical(render_payload) != render_id
        or metadata.get("render_identity") != render_id
        or metadata.get("source_id") != row.get("source_id")
        or metadata.get("source_hash") != row.get("source_sha256")
        or metadata.get("page_number") != page
        or metadata.get("region") != region
        or metadata.get("sha256") != _bytes_hash(image)
        or metadata.get("recipe") != "png-rgb-72dpi-full-144dpi-region-v1"
        or metadata.get("media_type") != "image/png"
        or len(image) < 26
        or image[:8] != b"\x89PNG\r\n\x1a\n"
        or image[12:16] != b"IHDR"
        or struct.unpack(">II", image[16:24])
        != (metadata.get("pixel_width"), metadata.get("pixel_height"))
    ):
        bundle.failures.append("visual Evidence render binding is invalid")
        return
    evidence[str(row.get("identity"))] = row


def _captured_snapshot(
    bundle: _Bundle,
    sources: dict[str, tuple[str, bytes, tuple[str, ...], str]],
    trial_id: object,
) -> str | None:
    captured = bundle.names.get("captured_batch.json")
    if captured is None or not isinstance(trial_id, str):
        return None
    preflight = bundle.names.get("preflight.json")
    candidates = {
        row.get("identity"): row
        for row in (preflight or {}).get("candidates", [])
        if isinstance(row, dict) and isinstance(row.get("identity"), str)
    }
    source_rows = [
        row
        for row in captured.get("sources", [])
        if (
            isinstance(row, dict)
            and row.get("trial_id") == trial_id
            and isinstance(row.get("candidate_identity"), str)
            and isinstance(row.get("role"), str)
            and isinstance(candidates.get(row["candidate_identity"]), dict)
        )
    ]
    if not source_rows:
        return None
    ordered = sorted(
        source_rows,
        key=lambda row: (
            int(row["role"] != "main_article"),
            Path(str(candidates[row["candidate_identity"]].get("relative_path", ""))).name.casefold(),
            row["candidate_identity"],
        ),
    )
    ids = tuple(row["candidate_identity"] for row in ordered)
    if any(source_id not in sources for source_id in ids):
        return None
    return _canonical(
        {
            "trial_id": trial_id,
            "scope_kind": "captured_batch",
            "scope_hash": captured.get("identity"),
            "source_ids": ids,
            "source_hashes": tuple(_bytes_hash(sources[source_id][1]) for source_id in ids),
            "projection_hashes": tuple(sources[source_id][3] for source_id in ids),
            "tokenizer": "unicode61_casefold_no_diacritics_v1",
            "ordering": "authoritative_source_role_label_id_page_v1",
        }
    )


def _valid_region(value: object) -> bool:
    return value is None or (
        isinstance(value, (list, tuple))
        and len(value) == 4
        and all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in value)
        and 0 <= value[0] < value[2] <= 1
        and 0 <= value[1] < value[3] <= 1
    )


def _assessed(
    bundle: _Bundle,
    summary: dict[str, Any],
    proposal: dict[str, Any],
    evidence: dict[str, dict[str, Any]],
) -> None:
    approved = bundle.names.get("approved_batch.json")
    if approved is None:
        bundle.failures.append("Approved Batch is unavailable")
        return
    base = {key: approved.get(key) for key in ("review", "acknowledgment", "dispositions")}
    if _canonical(base) != approved.get("identity") or approved.get("review") != proposal.get(
        "identity"
    ):
        bundle.failures.append("Approved Batch identity or Proposal chain is invalid")
    if summary["approved_batch"].get("identity") != approved.get("identity"):
        bundle.failures.append("finalization does not bind Approved Batch")
    ack = bundle.names.get("proposal_ack.json")
    ack_fields = ("record", "authority", "purpose", "caller", "observed_at")
    if (
        ack is None
        or ack.get("authority") != "researcher"
        or ack.get("purpose") != "proposal"
        or not str(ack.get("caller", "")).startswith(("cli:", "server:"))
        or not ack.get("observed_at")
    ):
        bundle.failures.append(
            "Proposal acknowledgment authority, purpose, caller, or time is invalid"
        )
    elif (
        _canonical({key: ack.get(key) for key in ack_fields}) != ack.get("identity")
        or ack.get("identity") != approved.get("acknowledgment")
        or ack.get("record") != _ref_record("proposal_review", proposal.get("identity"))
    ):
        bundle.failures.append("Proposal acknowledgment identity or binding is invalid")
    rows = [
        row
        for row in bundle.records.values()
        if row.get("kind") == "domain_candidate" and "active_hash" in row
    ]
    domains: dict[str, dict[str, Any]] = {}
    for row in rows:
        fields = (
            "kind",
            "packet",
            "trial_id",
            "result_id",
            "domain_id",
            "draft",
            "proposed_judgment",
            "inactive_questions",
            "evidence_bindings",
            "scientific_pack",
            "policy_pack",
        )
        if _canonical({key: row.get(key) for key in fields}) != row.get("identity"):
            bundle.failures.append("Domain candidate identity is invalid")
            continue
        if not isinstance(row.get("evidence_bindings"), list) or not row["evidence_bindings"]:
            bundle.failures.append("Domain candidate must have nonempty evidence bindings")
            continue
        if (
            row.get("scientific_pack") != SCIENTIFIC_PACK.content_hash
            or row.get("policy_pack") != MAINTAINER_POLICY_PACK.content_hash
        ):
            bundle.failures.append("Domain candidate does not bind the known pack catalog")
        if _canonical(
            {"candidate": row["identity"], "revision": row.get("active_revision")}
        ) != row.get("active_hash"):
            bundle.failures.append("Domain checkpoint identity is invalid")
        if _domain_oracle(row) != row.get("proposed_judgment"):
            bundle.failures.append("Domain checkpoint deterministic judgment is invalid")
        packet_ref = row.get("packet")
        packet_id = _ref(packet_ref, "work_packet")
        packet = bundle.records.get(packet_id or "")
        if (
            packet is None
            or _canonical(
                {
                    key: packet.get(key)
                    for key in (
                        "kind",
                        "approved_batch",
                        "trial_id",
                        "result_id",
                        "domain_id",
                        "active_question_ids",
                        "allowed_question_ids",
                        "stable_aliases",
                        "prior_domain_hashes",
                        "scientific_pack",
                        "policy_pack",
                    )
                }
            )
            != packet_id
            or packet.get("approved_batch", {}).get("identity") != approved.get("identity")
            or any(
                packet.get(key) != row.get(key) for key in ("trial_id", "result_id", "domain_id")
            )
            or packet.get("scientific_pack") != SCIENTIFIC_PACK.content_hash
            or packet.get("policy_pack") != MAINTAINER_POLICY_PACK.content_hash
            or packet.get("scientific_pack") != row.get("scientific_pack")
            or packet.get("policy_pack") != row.get("policy_pack")
        ):
            bundle.failures.append("Domain work packet, Batch binding, or pack basis is invalid")
        for binding in row.get("evidence_bindings", []):
            reference = binding.get("evidence") if isinstance(binding, dict) else None
            evidence_id = _evidence_ref(reference)
            record = evidence.get(evidence_id or "")
            if (
                not isinstance(binding, dict)
                or not isinstance(reference, dict)
                or not isinstance(binding.get("claim"), str)
                or not binding["claim"].strip()
                or record is None
                or record.get("trial_id") != row.get("trial_id")
                or reference.get("identity") != evidence_id
            ):
                bundle.failures.append(
                    "Domain evidence binding is missing, unrelated, or unprovenanced"
                )
        domain = str(row.get("domain_id"))
        if domain in domains:
            bundle.failures.append("duplicate active Domain checkpoint")
        domains[domain] = row
    required = {
        "domain:randomization",
        "domain:deviations",
        "domain:missing",
        "domain:measurement",
        "domain:selection",
    }
    if set(domains) != required:
        bundle.failures.append("assessed Trial does not have exactly five Domain checkpoints")
        return
    judgments = [str(row.get("proposed_judgment")) for row in domains.values()]
    overall = _overall_judgment(judgments)
    assessed = [row for row in summary["trials"] if row.get("disposition") == "assessed"]
    if len(assessed) != 1:
        bundle.failures.append("release assessed outcome must have assessed count one")
        return
    terminal = bundle.names.get(f"trial-outcome-{assessed[0].get('trial_id')}.json")
    snap_id = _ref(assessed[0].get("snapshot"), "assessment_snapshot")
    snapshot = bundle.records.get(snap_id or "")
    synthesis_id = _ref((snapshot or {}).get("synthesis"), "trial_synthesis")
    synthesis = bundle.records.get(synthesis_id or "")
    if (
        terminal is None
        or snapshot is None
        or terminal.get("snapshot", {}).get("identity") != snap_id
    ):
        bundle.failures.append("assessed terminal/snapshot chain is unavailable")
    elif snapshot.get("proposed_overall") != overall or snapshot.get("final_judgment") != overall:
        bundle.failures.append("AssessmentSnapshot deterministic overall is invalid")
    else:
        fields = (
            "synthesis",
            "checkpoint_hashes",
            "proposed_overall",
            "final_judgment",
            "caller",
            "observed_at",
        )
        if _canonical({key: snapshot.get(key) for key in fields}) != snapshot.get("identity"):
            bundle.failures.append("AssessmentSnapshot identity is invalid")
        synthesis_fields = (
            "approved_batch",
            "trial_id",
            "result_id",
            "checkpoint_hashes",
            "checkpoint_judgments",
            "proposed_overall",
            "combined_concerns",
        )
        if (
            synthesis is None
            or _canonical(
                {
                    key: (False if key == "combined_concerns" else synthesis.get(key))
                    for key in synthesis_fields
                }
            )
            != synthesis.get("identity")
            or synthesis.get("checkpoint_hashes") != snapshot.get("checkpoint_hashes")
            or {tuple(row) for row in synthesis.get("checkpoint_hashes", [])}
            != {(domain, value.get("active_hash")) for domain, value in domains.items()}
        ):
            bundle.failures.append("synthesis/checkpoint identity chain is invalid")
        terminal_fields = (
            "synthesis",
            "trial_id",
            "disposition",
            "reason",
            "failure_cause",
            "missing_facts",
            "available_evidence",
            "retained_checkpoints",
            "caller",
            "observed_at",
            "snapshot",
            "transition",
        )
        if (
            terminal.get("kind") != "trial_terminal"
            or _canonical({key: terminal.get(key) for key in terminal_fields})
            != terminal.get("identity")
            or assessed[0].get("outcome", {}).get("identity") != terminal.get("identity")
        ):
            bundle.failures.append("assessed terminal identity is invalid")
        else:
            finish_ack = next(
                (
                    row
                    for row in bundle.records.values()
                    if row.get("kind") == "review_ack"
                    and row.get("purpose") == "trial_finish"
                    and row.get("record") == _ref_record("trial_synthesis", synthesis_id)
                ),
                None,
            )
            finish_ack_payload = (
                {
                    key: finish_ack.get(key)
                    for key in ("record", "authority", "purpose", "caller", "observed_at")
                }
                if finish_ack is not None
                else None
            )
            if (
                finish_ack is None
                or finish_ack.get("authority") != "researcher"
                or not str(finish_ack.get("caller", "")).startswith(("cli:", "server:"))
                or _canonical(finish_ack_payload) != finish_ack.get("identity")
            ):
                bundle.failures.append("assessed Trial finish acknowledgment chain is invalid")


def _needs_input(bundle: _Bundle, summary: dict[str, Any], proposal: dict[str, Any]) -> None:
    """Validate the preapproval terminal separately from the AE Result card."""
    approved = bundle.names.get("approved_batch.json")
    ack = bundle.names.get("proposal_ack.json")
    if approved is None or ack is None:
        bundle.failures.append("AE Approved Batch or Proposal acknowledgment is unavailable")
        return
    base = {key: approved.get(key) for key in ("review", "acknowledgment", "dispositions")}
    if _canonical(base) != approved.get("identity") or approved.get("review") != proposal.get(
        "identity"
    ):
        bundle.failures.append("AE Approved Batch identity or Proposal binding is invalid")
    ack_fields = ("record", "authority", "purpose", "caller", "observed_at")
    if (
        ack.get("authority") != "researcher"
        or ack.get("purpose") != "proposal"
        or not str(ack.get("caller", "")).startswith(("cli:", "server:"))
        or _canonical({key: ack.get(key) for key in ack_fields}) != ack.get("identity")
        or ack.get("identity") != approved.get("acknowledgment")
        or ack.get("record") != _ref_record("proposal_review", proposal.get("identity"))
    ):
        bundle.failures.append("AE Proposal acknowledgment chain is invalid")
    terminals = [row for row in summary["trials"] if row.get("disposition") == "needs_input"]
    if len(terminals) != 1:
        bundle.failures.append("AE needs-input terminal count is invalid")
        return
    terminal = bundle.names.get(f"trial-outcome-{terminals[0].get('trial_id')}.json")
    fields = ("trial_id", "disposition", "reason", "missing_facts", "evidence", "acknowledgment")
    if (
        terminal is None
        or terminal.get("kind") != "trial_terminal"
        or terminal.get("disposition") != "needs_input"
        or terminal.get("reason") != "comparator_unavailable"
        or _canonical({key: terminal.get(key) for key in fields}) != terminal.get("identity")
        or _ref(terminal.get("acknowledgment"), "review_ack") != ack.get("identity")
        or terminals[0].get("outcome", {}).get("identity") != terminal.get("identity")
    ):
        bundle.failures.append(
            "AE needs-input terminal identity, reason, or acknowledgment is invalid"
        )
    if summary.get("presentation", {}).get("code") != "finalized_zero_assessed":
        bundle.failures.append("AE finalization presentation is invalid")


def verify_artifact(
    root: str | Path, objective: ObjectiveFactManifest, outcome_key: str
) -> VerificationResult:
    """Verify bytes, identities, workflow chains, and independent RoB 2 logic."""
    failures: list[str] = []
    bundle = _Bundle(Path(root), failures)
    bundle.load()
    summary, proposal = _summary(bundle), _proposal(bundle, outcome_key, objective)
    expected = objective.outcome(outcome_key).expected_terminal
    if summary is not None and proposal is not None:
        evidence = _sources_and_evidence(bundle, proposal)
        if expected == "assessed":
            _assessed(bundle, summary, proposal, evidence)
        elif summary.get("counts") != {
            "total": 1,
            "pending": 0,
            "assessed": 0,
            "needs_input": 1,
            "failed": 0,
        }:
            failures.append("adverse-events final counts are invalid")
        else:
            _needs_input(bundle, summary, proposal)
    if not (bundle.root / "report.html").is_file():
        failures.append("verified report artifact is unavailable")
    receipt = bundle.names.get("finalization-receipt.json")
    if (
        receipt is None
        or receipt.get("outcome") != "committed"
        or receipt.get("summary") != (summary or {}).get("identity")
        or receipt.get("kind") != "finalization_receipt"
        or _canonical({"summary": receipt.get("summary"), "outcome": receipt.get("outcome")})
        != receipt.get("identity")
    ):
        failures.append("durable finalization receipt is unavailable or unbound")
    try:
        report = (bundle.root / "report.html").read_text(encoding="utf-8")
        if summary is None or summary["presentation"]["summary"] not in report:
            failures.append("report does not bind the finalized summary")
    except (OSError, KeyError, TypeError):
        failures.append("verified report artifact is unavailable")
    return VerificationResult(not failures, tuple(failures), (outcome_key,) if proposal else ())
