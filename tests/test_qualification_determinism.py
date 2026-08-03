from datetime import UTC, datetime
from pathlib import Path

from rob2_kit.application.determinism import QualificationDeterminism
from rob2_kit.application.run_engine import RunEngine


def test_qualification_determinism_has_stable_time_ids_and_run_identity() -> None:
    determinism = QualificationDeterminism(datetime(2026, 8, 3, tzinfo=UTC))

    assert determinism.now() == datetime(2026, 8, 3, tzinfo=UTC)
    identifiers = determinism.event_identifiers("operation:one", "revision:one", 1)
    assert identifiers == determinism.event_identifiers("operation:one", "revision:one", 1)
    assert identifiers[0].startswith("operation:")
    assert identifiers[1].startswith("event:")
    engine = RunEngine(determinism=determinism)
    assert engine._new_run_id(Path("one"), 0) == engine._new_run_id(Path("two"), 0)


def test_default_run_engine_keeps_project_scoped_run_identity() -> None:
    engine = RunEngine()

    assert engine._new_run_id(Path("one"), 0) != engine._new_run_id(Path("two"), 0)
