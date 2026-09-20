"""Provider-independent, privacy-safe held-out evaluation utilities."""

from .adjudication import (
    AdjudicationClassification,
    AdjudicationSidecar,
    read_sidecar,
    validate_sidecar,
    write_sidecar,
)
from .coverage import CoverageRecord, PremiseCoverage, RecoveryAction, RecoveryWindow
from .harness import (
    COMPARISON_RUN_SCHEMA,
    COMPARISON_SCHEMA,
    EVENT_TYPES,
    SCHEMA,
    evaluate_fixture,
    run_comparison,
    validate_comparison_config,
    validate_split_isolation,
)
from .observations import (
    MANIFEST_SCHEMA as OBSERVATION_MANIFEST_SCHEMA,
)
from .observations import (
    ObservationImportError,
    dump_observations,
    import_observations,
    load_manifest,
)
from .qualification_report import (
    SCHEMA as QUALIFICATION_REPORT_SCHEMA,
)
from .qualification_report import identity as qualification_identity
from .qualification_report import promotion_decision
from .qualification_report import validate as validate_qualification_report

__all__ = [
    "EVENT_TYPES",
    "COMPARISON_SCHEMA",
    "COMPARISON_RUN_SCHEMA",
    "SCHEMA",
    "OBSERVATION_MANIFEST_SCHEMA",
    "ObservationImportError",
    "dump_observations",
    "evaluate_fixture",
    "run_comparison",
    "import_observations",
    "load_manifest",
    "validate_split_isolation",
    "validate_comparison_config",
    "QUALIFICATION_REPORT_SCHEMA",
    "qualification_identity",
    "promotion_decision",
    "validate_qualification_report",
    "AdjudicationClassification",
    "AdjudicationSidecar",
    "read_sidecar",
    "validate_sidecar",
    "write_sidecar",
    "CoverageRecord",
    "PremiseCoverage",
    "RecoveryAction",
    "RecoveryWindow",
]
