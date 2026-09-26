"""Provider-independent, privacy-safe held-out evaluation utilities."""

from .adjudication import (
    AdjudicationClassification,
    AdjudicationSidecar,
    read_sidecar,
    validate_sidecar,
    write_sidecar,
)
from .cohort import (
    COHORT_REVISION,
    AgreementSampleEntry,
    CohortCell,
    CohortClassification,
    CohortLabel,
    CohortManifest,
    ModelAccess,
    PublishedTotals,
    ReviewerProvenance,
    content_hash,
    read_cohort,
    select_agreement_sample,
    summarize,
    validate_cohort,
    write_cohort,
)
from .cohort import DOMAINS as COHORT_DOMAINS
from .cohort import OUTCOMES as COHORT_OUTCOMES
from .cohort import SCHEMA as COHORT_SCHEMA
from .coverage import CoverageRecord, PremiseCoverage, RecoveryAction, RecoveryWindow
from .harness import (
    COMPARISON_RUN_SCHEMA,
    COMPARISON_SCHEMA,
    EVENT_TYPES,
    QUALIFICATION_COMPARISON_RUN_SCHEMA,
    QUALIFICATION_COMPARISON_SCHEMA,
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
    QUALIFICATION_SCHEMA,
    promotion_decision,
)
from .qualification_report import (
    SCHEMA as QUALIFICATION_REPORT_SCHEMA,
)
from .qualification_report import identity as qualification_identity
from .qualification_report import validate as validate_qualification_report

__all__ = [
    "EVENT_TYPES",
    "COMPARISON_SCHEMA",
    "COMPARISON_RUN_SCHEMA",
    "QUALIFICATION_COMPARISON_SCHEMA",
    "QUALIFICATION_COMPARISON_RUN_SCHEMA",
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
    "QUALIFICATION_SCHEMA",
    "qualification_identity",
    "promotion_decision",
    "validate_qualification_report",
    "AdjudicationClassification",
    "AdjudicationSidecar",
    "read_sidecar",
    "validate_sidecar",
    "write_sidecar",
    "COHORT_REVISION",
    "COHORT_DOMAINS",
    "COHORT_OUTCOMES",
    "COHORT_SCHEMA",
    "AgreementSampleEntry",
    "CohortCell",
    "CohortClassification",
    "CohortLabel",
    "CohortManifest",
    "ModelAccess",
    "PublishedTotals",
    "ReviewerProvenance",
    "content_hash",
    "read_cohort",
    "select_agreement_sample",
    "summarize",
    "validate_cohort",
    "write_cohort",
    "CoverageRecord",
    "PremiseCoverage",
    "RecoveryAction",
    "RecoveryWindow",
]
