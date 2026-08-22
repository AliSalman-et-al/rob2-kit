"""Persistent Proposal drafts with a deliberately small JSON-Patch subset."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ._state import identity, read_json, write_json


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DraftPatch(_Closed):
    op: Literal["add", "replace", "remove", "test"]
    path: str = Field(pattern=r"^(?:|/(?:[^~/]|~[01])+(?:/(?:[^~/]|~[01])+)*)$")
    value: object | None = None

    @model_validator(mode="after")
    def value_matches_operation(self) -> DraftPatch:
        if self.op in {"add", "replace", "test"} and "value" not in self.model_fields_set:
            raise ValueError(f"{self.op} requires value")
        if self.op == "remove" and "value" in self.model_fields_set:
            raise ValueError("remove does not accept value")
        return self


class ProposalDraftCommand(_Closed):
    draft_operation: Literal["create", "patch", "read", "submit"]
    draft_id: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    proposal: dict[str, object] | None = None
    patches: tuple[DraftPatch, ...] = ()

    @model_validator(mode="after")
    def command_is_complete(self) -> ProposalDraftCommand:
        if self.draft_operation == "create" and self.proposal is None:
            raise ValueError("create requires proposal")
        if self.draft_operation in {"patch", "read", "submit"} and self.draft_id is None:
            raise ValueError(f"{self.draft_operation} requires draft_id")
        if self.draft_operation == "patch" and not self.patches:
            raise ValueError("patch requires at least one patch operation")
        return self


class ProposalDraftReceipt(_Closed):
    outcome: Literal["draft"] = "draft"
    draft_id: str
    proposal: dict[str, object]
    applied_patches: int = Field(ge=0)
    next_action: Literal["patch_or_submit"] = "patch_or_submit"


def _file(draft_id: str) -> str:
    return f"proposal-draft-{draft_id.removeprefix('sha256:')}.json"


def _decode(pointer: str) -> list[str]:
    if pointer == "":
        return []
    return [part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")]


def _parent(document: object, pointer: str) -> tuple[object, str]:
    parts = _decode(pointer)
    if not parts:
        raise ValueError("root replacement is not supported; create a new draft instead")
    current = document
    for part in parts[:-1]:
        if isinstance(current, dict):
            if part not in current:
                raise ValueError(f"patch path does not exist: {pointer}")
            current = current[part]
        elif isinstance(current, list):
            current = current[int(part)]
        else:
            raise ValueError(f"patch path traverses a scalar: {pointer}")
    return current, parts[-1]


def _get(document: object, pointer: str) -> object:
    current = document
    for part in _decode(pointer):
        if isinstance(current, dict):
            if part not in current:
                raise ValueError(f"patch path does not exist: {pointer}")
            current = current[part]
        elif isinstance(current, list):
            current = current[int(part)]
        else:
            raise ValueError(f"patch path traverses a scalar: {pointer}")
    return current


def apply_patches(
    document: dict[str, object], patches: tuple[DraftPatch, ...]
) -> dict[str, object]:
    result: object = deepcopy(document)
    for patch in patches:
        if patch.op == "test":
            if _get(result, patch.path) != patch.value:
                raise ValueError(f"draft test operation failed: {patch.path}")
            continue
        parent, key = _parent(result, patch.path)
        if isinstance(parent, dict):
            if patch.op == "remove":
                if key not in parent:
                    raise ValueError(f"patch path does not exist: {patch.path}")
                del parent[key]
            elif patch.op == "replace":
                if key not in parent:
                    raise ValueError(f"patch path does not exist: {patch.path}")
                parent[key] = deepcopy(patch.value)
            else:
                parent[key] = deepcopy(patch.value)
        elif isinstance(parent, list):
            if key == "-" and patch.op == "add":
                parent.append(deepcopy(patch.value))
                continue
            index = int(key)
            if patch.op == "remove":
                del parent[index]
            elif patch.op == "replace":
                parent[index] = deepcopy(patch.value)
            else:
                parent.insert(index, deepcopy(patch.value))
        else:
            raise ValueError(f"patch parent is scalar: {patch.path}")
    if not isinstance(result, dict):
        raise ValueError("Proposal draft must remain a JSON object")
    return result


def create_draft(workspace: str | Path, proposal: dict[str, object]) -> ProposalDraftReceipt:
    draft_id = identity({"proposal": proposal})
    write_json(
        workspace,
        _file(draft_id),
        {"kind": "proposal_draft", "identity": draft_id, "proposal": proposal},
    )
    return ProposalDraftReceipt(draft_id=draft_id, proposal=proposal, applied_patches=0)


def read_draft(workspace: str | Path, draft_id: str) -> ProposalDraftReceipt:
    raw = read_json(workspace, _file(draft_id))
    if (
        not isinstance(raw, dict)
        or raw.get("identity") != draft_id
        or not isinstance(raw.get("proposal"), dict)
    ):
        raise ValueError("Proposal draft is unavailable or stale")
    proposal = raw["proposal"]
    if identity({"proposal": proposal}) != draft_id:
        raise ValueError("Proposal draft identity is corrupt")
    return ProposalDraftReceipt(draft_id=draft_id, proposal=proposal, applied_patches=0)


def patch_draft(
    workspace: str | Path, draft_id: str, patches: tuple[DraftPatch, ...]
) -> ProposalDraftReceipt:
    current = read_draft(workspace, draft_id)
    proposal = apply_patches(current.proposal, patches)
    next_receipt = create_draft(workspace, proposal)
    return next_receipt.model_copy(update={"applied_patches": len(patches)})