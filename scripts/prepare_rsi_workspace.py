"""Build a clean assessment workspace from an explicit source allowlist."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = "rob2-kit.rsi-case.v1"
ROLES = {"main_article", "registry", "supplement", "sap", "protocol", "other"}
SUPPORTED = {".pdf", ".docx", ".txt", ".md", ".csv", ".json"}
NCT_PATTERN = re.compile(r"NCT\d{8}")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_case(case_path: Path) -> dict[str, Any]:
    case_path = case_path.resolve(strict=True)
    case = json.loads(case_path.read_text(encoding="utf-8"))
    if not isinstance(case, dict) or case.get("schema") != SCHEMA:
        raise ValueError(f"case must use schema {SCHEMA}")
    required = {"schema", "trial", "requested_outcome", "sources"}
    if set(case) - (required | {"registry_capture", "approved_scope"}) or not required <= set(case):
        raise ValueError("case has missing or unknown fields")
    if not isinstance(case["trial"], str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._-]*", case["trial"]
    ):
        raise ValueError("trial must be a safe directory name")
    if not isinstance(case["requested_outcome"], str) or not case["requested_outcome"].strip():
        raise ValueError("requested_outcome must be non-empty")
    if not isinstance(case["sources"], list) or not case["sources"]:
        raise ValueError("sources must be a non-empty allowlist")
    return case


def _registry_identifier(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or NCT_PATTERN.fullmatch(value) is None:
        raise ValueError("registry_id must match NCT########")
    return value


def _source_path(base: Path, value: object) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError("source path must be a non-empty relative path")
    path = Path(value)
    if path.is_absolute():
        raise ValueError("source paths must be relative to the case manifest")
    resolved = (base / path).resolve(strict=True)
    # Evaluation manifests commonly live below ``eval/runs`` or
    # ``eval/reference`` while sharing the read-only corpus in
    # ``eval/reference/sources``. Allow that evaluation root, but keep the
    # default temporary-case behavior scoped to the manifest directory.
    evaluation_root = next(
        (parent / "eval" for parent in (base, *base.parents) if (parent / "eval").is_dir()),
        base,
    )
    if not resolved.is_file() or not resolved.is_relative_to(evaluation_root):
        raise ValueError(
            "source path must resolve to a file under the case manifest or evaluation root"
        )
    return resolved


def _toml_quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def prepare_workspace(case_file: Path, workspace: Path) -> dict[str, Any]:
    """Materialize only listed source bytes and return a provenance manifest."""
    case_file = case_file.resolve(strict=True)
    case = _load_case(case_file)
    workspace = workspace.resolve()
    if workspace.exists():
        raise ValueError("refusing to overwrite an existing assessment workspace")

    inputs = workspace / "input" / case["trial"]
    inputs.mkdir(parents=True)
    file_records: list[dict[str, str]] = []
    role_by_name: dict[str, str] = {}
    used_names: set[str] = set()
    try:
        for source in case["sources"]:
            if not isinstance(source, dict) or set(source) != {"path", "name", "role"}:
                raise ValueError("each source must contain exactly path, name, and role")
            name, role = source["name"], source["role"]
            if (
                not isinstance(name, str)
                or Path(name).name != name
                or name in {".", "..", "sources.toml"}
                or Path(name).suffix.lower() not in SUPPORTED
            ):
                raise ValueError("source name must be a supported plain filename")
            if not isinstance(role, str) or role not in ROLES or name in used_names:
                raise ValueError("source role is invalid or source filename is duplicated")
            used_names.add(name)
            role_by_name[name] = role
            source_path = _source_path(case_file.parent, source["path"])
            content = source_path.read_bytes()
            (inputs / name).write_bytes(content)
            file_records.append({"name": name, "role": role, "sha256": _sha256(content)})

        registry = case.get("registry_capture")
        registry_record = None
        if registry is not None:
            if (
                not isinstance(registry, dict)
                or set(registry) - {"path", "captured_at", "sha256", "provenance", "registry_id"}
                or not {"path", "captured_at", "sha256", "provenance"} <= set(registry)
            ):
                raise ValueError(
                    "registry_capture must contain path, captured_at, sha256, provenance"
                )
            if (
                not isinstance(registry["captured_at"], str)
                or not isinstance(registry["provenance"], str)
                or not registry["provenance"].strip()
            ):
                raise ValueError("registry capture time and provenance are required")
            try:
                captured_at = datetime.fromisoformat(registry["captured_at"].replace("Z", "+00:00"))
            except ValueError as error:
                raise ValueError("registry captured_at must be an ISO-8601 timestamp") from error
            if captured_at.tzinfo is None:
                raise ValueError("registry captured_at must include a timezone")
            if "registry.json" in used_names:
                raise ValueError("registry capture conflicts with an allowlisted source filename")
            path = _source_path(case_file.parent, registry["path"])
            data = path.read_bytes()
            digest = _sha256(data)
            if not isinstance(registry["sha256"], str) or digest != registry["sha256"].lower():
                raise ValueError("registry capture SHA-256 does not match supplied bytes")
            registry_id = _registry_identifier(registry.get("registry_id"))
            (inputs / "registry.json").write_bytes(data)
            file_records.append({"name": "registry.json", "role": "registry", "sha256": digest})
            registry_record = {
                "captured_at": registry["captured_at"],
                "sha256": digest,
                "capture_provenance": registry["provenance"],
                "replayed_at": datetime.now(UTC).isoformat(),
                "replay_provenance": (
                    "copied byte-for-byte from the case manifest; no registry request made"
                ),
            }
            if registry_id is not None:
                registry_record["registry_id"] = registry_id

        roles = dict(role_by_name)
        if registry_record is not None:
            roles["registry.json"] = "registry"
        source_lines: list[str] = []
        if registry_record is not None and registry_record.get("registry_id") is not None:
            source_lines += [
                "[registry]",
                f"nct = {_toml_quote(str(registry_record['registry_id']))}",
                'replay = "registry.json"',
                f"captured_at = {_toml_quote(str(registry_record['captured_at']))}",
                f"sha256 = {_toml_quote(str(registry_record['sha256']))}",
                f"provenance = {_toml_quote(str(registry_record['capture_provenance']))}",
                "",
            ]
        source_lines += ["[roles]"] + [
            f"{_toml_quote(name)} = {_toml_quote(role)}" for name, role in sorted(roles.items())
        ]
        (inputs / "sources.toml").write_text("\n".join(source_lines) + "\n", encoding="utf-8")
        # Validate the generated intake metadata before exposing it to the assessment tools.
        with (inputs / "sources.toml").open("rb") as stream:
            parsed = tomllib.load(stream)
        if parsed.get("roles") != roles:
            raise ValueError("failed to generate valid source role metadata")

        approved_scope = case.get("approved_scope")
        if approved_scope is not None and (
            not isinstance(approved_scope, str) or not approved_scope.strip()
        ):
            raise ValueError("approved_scope must be a non-empty string when supplied")
        manifest = {
            "schema": "rob2-kit.rsi-run-inputs.v1",
            "trial": case["trial"],
            "requested_outcome": case["requested_outcome"],
            "approved_scope": approved_scope,
            "sources": sorted(file_records, key=lambda item: item["name"]),
            "registry_capture": registry_record,
        }
        return manifest
    except BaseException:
        shutil.rmtree(workspace, ignore_errors=True)
        raise


def approved_scope_record(workspace: Path, requested_scope: str | None) -> dict[str, Any] | None:
    """Return scope fingerprints only after the exact Proposal Review was approved."""
    from rob2_kit.application._state import _identity, _root, _state
    from rob2_kit.application.finalization import _valid_proposal_gate

    state = _state(_root(workspace))
    proposal = state.get("proposal")
    review = state.get("proposal_review")
    acknowledgment = state.get("proposal_acknowledgment")
    if (
        not _valid_proposal_gate(review, acknowledgment, proposal, _identity)
        or not isinstance(proposal, dict)
        or not isinstance(review, dict)
        or not isinstance(acknowledgment, dict)
    ):
        return None
    payload = proposal.get("payload")
    results = payload.get("results") if isinstance(payload, dict) else None
    if (
        not isinstance(results, list)
        or not results
        or any(not isinstance(result, dict) for result in results)
    ):
        raise ValueError("approved Proposal has no Result records")
    return {
        "schema": "rob2-kit.rsi-approved-scope.v1",
        "case_requested_scope": requested_scope,
        "proposal_identity": proposal["identity"],
        "review_identity": review["identity"],
        "approval_identity": acknowledgment["identity"],
        "approved_at": acknowledgment["observed_at"],
        "results": [
            {
                "identity": _identity(result),
                "trial_id": result["trial_id"],
                "kind": result["kind"],
                "target_scope_identity": _identity(result["target"]),
                "reported_scope_identity": _identity(result["reported"]),
            }
            for result in results
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", type=Path, required=True, help="Frozen JSON case manifest")
    parser.add_argument("--workspace", type=Path, required=True, help="New empty workspace path")
    args = parser.parse_args()
    print(json.dumps(prepare_workspace(args.case, args.workspace), sort_keys=True))


if __name__ == "__main__":
    main()
