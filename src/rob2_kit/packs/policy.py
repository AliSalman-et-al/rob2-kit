"""Maintainer retrieval policy.  This is not Cochrane guidance."""

from rob2_kit.models import LexicalSeed, PolicyPack, sha256

_CONTENT = {
    "id": "rob2-kit.retrieval-policy",
    "version": "1.0.0",
    "attribution": "rob2-kit maintainers; not attributed to Cochrane",
    "lexical_seeds": (
        LexicalSeed(id="randomization", terms=("random", "allocation", "conceal")),
        LexicalSeed(id="missing", terms=("missing", "withdraw", "loss to follow-up")),
        LexicalSeed(id="selection", terms=("protocol", "analysis plan", "outcome")),
    ),
    "source_priority": (
        "main_article",
        "registry",
        "protocol",
        "sap",
        "supplement",
        "secondary_report",
    ),
    "contradiction_checks": (
        "retain material contradicting evidence",
        "compare prespecification sources with reports",
    ),
    "selective_vision": (
        "render tables, CONSORT diagrams, figures, and spatial footnotes "
        "only when text is insufficient",
    ),
}
MAINTAINER_POLICY_PACK = PolicyPack(**_CONTENT, content_hash=sha256(_CONTENT))


def load_policy_pack(data: dict[str, object]) -> PolicyPack:
    """Validate a serialized policy pack and reject a mismatched declared hash."""
    pack = PolicyPack.model_validate(data)
    content = pack.model_dump(mode="python", exclude={"content_hash"})
    if pack.content_hash != sha256(content):
        raise ValueError("policy pack content hash does not match its content")
    return pack
