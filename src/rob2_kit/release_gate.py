"""Machine-verifiable evidence map for the public-v1 release blockers."""

from __future__ import annotations

import ast
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path


class ReleaseGateError(ValueError):
    """The public-v1 release evidence manifest is incomplete or unsafe."""


@dataclass(frozen=True)
class ManualCheck:
    check_id: str
    owner: str
    evidence_slot: str


@dataclass(frozen=True)
class Blocker:
    blocker_id: str
    description: str
    evidence: tuple[str, ...]
    manual_checks: tuple[ManualCheck, ...]


@dataclass(frozen=True)
class Fixture:
    fixture_id: str
    kind: str
    path: Path
    description: str
    evidence: str


@dataclass(frozen=True)
class ReleaseGate:
    blockers: dict[str, Blocker]
    fixtures: dict[str, Fixture]


def load_release_gate(root: Path) -> ReleaseGate:
    root = root.resolve()
    manifest_path = root / "release-gate.toml"
    try:
        raw = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ReleaseGateError(f"cannot load {manifest_path}: {error}") from error

    if raw.get("version") != 1:
        raise ReleaseGateError("release gate version must be 1")

    blockers: dict[str, Blocker] = {}
    for blocker_entry in raw.get("blockers", []):
        blocker_id = _required(blocker_entry, "id")
        evidence = tuple(blocker_entry.get("evidence", ()))
        if not evidence:
            raise ReleaseGateError(f"blocker {blocker_id!r} has no evidence")
        for reference in evidence:
            _validate_test_reference(root, reference)
        manual_checks = tuple(
            ManualCheck(
                check_id=_required(manual_check_entry, "id"),
                owner=_required(manual_check_entry, "owner"),
                evidence_slot=_required(manual_check_entry, "evidence_slot"),
            )
            for manual_check_entry in blocker_entry.get("manual_checks", ())
        )
        if blocker_id in blockers:
            raise ReleaseGateError(f"duplicate blocker {blocker_id!r}")
        blockers[blocker_id] = Blocker(
            blocker_id=blocker_id,
            description=_required(blocker_entry, "description"),
            evidence=evidence,
            manual_checks=manual_checks,
        )

    fixtures: dict[str, Fixture] = {}
    for fixture_entry in raw.get("fixtures", []):
        fixture_id = _required(fixture_entry, "id")
        relative = _required(fixture_entry, "path").replace("\\", "/")
        description = _required(fixture_entry, "description")
        fixture_metadata_text = f"{relative} {description}".casefold()
        if (
            "eval/reference" in fixture_metadata_text
            or "provisional reference" in fixture_metadata_text
        ):
            raise ReleaseGateError(
                f"fixture {fixture_id!r} uses private or Provisional reference material"
            )
        path = (root / relative).resolve()
        fixture_roots = (
            (root / "tests" / "public_fixtures").resolve(),
            (root / "tests" / "visual_fixtures").resolve(),
        )
        if not any(path.is_relative_to(fixture_root) for fixture_root in fixture_roots):
            raise ReleaseGateError(f"fixture {fixture_id!r} is outside distributable fixtures")
        if not path.is_file():
            raise ReleaseGateError(f"fixture {fixture_id!r} is missing: {relative}")
        evidence = _required(fixture_entry, "evidence")
        _validate_test_reference(root, evidence)
        if fixture_id in fixtures:
            raise ReleaseGateError(f"duplicate fixture {fixture_id!r}")
        fixtures[fixture_id] = Fixture(
            fixture_id=fixture_id,
            kind=_required(fixture_entry, "kind"),
            path=path,
            description=description,
            evidence=evidence,
        )

    if not blockers:
        raise ReleaseGateError("release gate has no blockers")
    if not fixtures:
        raise ReleaseGateError("release gate has no fixtures")
    return ReleaseGate(blockers=blockers, fixtures=fixtures)


def _required(manifest_entry: dict[str, object], key: str) -> str:
    value = manifest_entry.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ReleaseGateError(f"missing non-empty {key!r}")
    return value


def _validate_test_reference(root: Path, reference: object) -> None:
    if not isinstance(reference, str) or "::" not in reference:
        raise ReleaseGateError(f"automated evidence must be a pytest node ID: {reference!r}")
    relative, test_name = reference.split("::", 1)
    if not relative.startswith("tests/") or not test_name.startswith("test_"):
        raise ReleaseGateError(f"invalid pytest evidence node ID {reference!r}")
    test_path = root / relative
    if not test_path.is_file():
        raise ReleaseGateError(f"missing pytest evidence file {relative!r}")
    try:
        tree = ast.parse(test_path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as error:
        raise ReleaseGateError(f"cannot inspect pytest evidence {reference!r}: {error}") from error
    functions = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    if test_name.split("[", 1)[0] not in functions:
        raise ReleaseGateError(f"missing pytest evidence test {reference!r}")


def main() -> None:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    gate = load_release_gate(root)
    print(
        f"public-v1 release gate valid: "
        f"{len(gate.blockers)} blockers, {len(gate.fixtures)} fixtures"
    )


if __name__ == "__main__":
    main()
