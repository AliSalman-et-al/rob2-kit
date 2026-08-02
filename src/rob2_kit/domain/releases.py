"""Pack and project-policy release contracts."""

from enum import StrEnum

from pydantic import Field

from rob2_kit.domain.revisions import (
    ContentHash,
    Identifier,
    RecordReference,
    Revision,
    SchemaVersion,
)


class PackKind(StrEnum):
    LOGIC = "logic"
    GUIDANCE = "guidance"


class PolicyKind(StrEnum):
    REVIEW_POLICY = "review_policy"
    EVIDENCE_SEARCH_POLICY = "evidence_search_policy"
    RECOVERY_POLICY = "recovery_policy"
    PARSER_QUALITY_POLICY = "parser_quality_policy"
    REUSE_POLICY = "reuse_policy"
    CONTEXT_ASSEMBLY_POLICY = "context_assembly_policy"
    PROJECT_RULES = "project_rules"


class PackRelease(Revision):
    dependency_roles = {
        "inventory": "dependency:release-item",
        "compatible_releases": "dependency:compatible-release",
    }
    kind: PackKind
    family_id: Identifier
    release_id: str = Field(min_length=1)
    canonical_content_hash: ContentHash
    required_schema_version: SchemaVersion
    inventory: tuple[RecordReference, ...]
    compatible_releases: tuple[RecordReference, ...] = ()


class PolicyRelease(Revision):
    dependency_roles = {"inventory": "dependency:release-item"}
    kind: PolicyKind
    family_id: Identifier
    release_id: str = Field(min_length=1)
    canonical_content_hash: ContentHash
    required_schema_version: SchemaVersion
    inventory: tuple[RecordReference, ...]


class ProjectRule(Revision):
    scope: str = Field(min_length=1)
    conditions: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    authored_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
