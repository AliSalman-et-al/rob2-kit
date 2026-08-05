"""Public replay fixtures and host-neutral normalized traces.

The evaluation surface deliberately contains no model output or credentials.  It
describes a small synthetic dossier and the semantic fields that are safe to
compare across Harnesses.  Raw host transcripts stay outside this package.
"""

from .dossier import (
    DossierOverlay,
    DossierSource,
    Prompt,
    PublicDossier,
    load_public_dossier,
)
from .golden import GoldenAcceptanceRequired, accept_golden, semantic_diff
from .traces import (
    NormalizedCall,
    NormalizedTrace,
    TraceFinal,
    TraceSignals,
    normalize_trace,
)
from .verifier import (
    BlindedVerifierContext,
    ReconsiderationRequest,
    TriggerFacts,
    VerifierEvaluation,
    VerifierReply,
    VerifierUnavailable,
    compare_verifier_modes,
    evaluate_blinded_verifier,
    replay_verifier_fixture,
)

__all__ = [
    "DossierOverlay",
    "DossierSource",
    "GoldenAcceptanceRequired",
    "NormalizedCall",
    "NormalizedTrace",
    "Prompt",
    "PublicDossier",
    "TraceFinal",
    "TraceSignals",
    "accept_golden",
    "BlindedVerifierContext",
    "ReconsiderationRequest",
    "TriggerFacts",
    "VerifierEvaluation",
    "VerifierReply",
    "VerifierUnavailable",
    "compare_verifier_modes",
    "evaluate_blinded_verifier",
    "replay_verifier_fixture",
    "load_public_dossier",
    "normalize_trace",
    "semantic_diff",
]
