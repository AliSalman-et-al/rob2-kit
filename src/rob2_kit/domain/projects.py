"""Project manifest contracts."""

from pydantic import Field

from rob2_kit.domain.revisions import Identifier, RecordReference, Revision


class OutcomeTarget(Revision):
    name: str = Field(min_length=1)
    time_point: str = Field(min_length=1)


class ProjectManifestRevision(Revision):
    dependency_roles = {
        "outcome_targets": "dependency:outcome-target",
        "logic_release": "dependency:logic-release",
        "guidance_release": "dependency:guidance-release",
        "policy_releases": "dependency:policy-release",
    }
    project_name: str = Field(min_length=1)
    outcome_targets: tuple[RecordReference, ...]
    supported_variant: Identifier
    source_adapters: tuple[Identifier, ...] = ()
    logic_release: RecordReference
    guidance_release: RecordReference
    policy_releases: tuple[RecordReference, ...]
