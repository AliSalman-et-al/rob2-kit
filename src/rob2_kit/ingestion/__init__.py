"""Project initialization and source-ingestion public boundary."""

from rob2_kit.ingestion.project import (
    BoundedZipError,
    DocumentParser,
    LiteParseAdapter,
    OutcomeTarget,
    PageExtraction,
    ParserResult,
    ProjectInitialization,
    ProjectManifest,
    ResultCandidate,
    ReviewFinding,
    SourceParseError,
    TrialInitialization,
    initialize_project,
    read_bounded_zip,
)

__all__ = [
    "BoundedZipError",
    "DocumentParser",
    "LiteParseAdapter",
    "OutcomeTarget",
    "PageExtraction",
    "ParserResult",
    "ProjectInitialization",
    "ProjectManifest",
    "ResultCandidate",
    "ReviewFinding",
    "SourceParseError",
    "TrialInitialization",
    "initialize_project",
    "read_bounded_zip",
]
