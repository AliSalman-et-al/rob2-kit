import pytest

from rob2_kit.workflow_models import MechanicalRepairRevision


def test_mechanical_repair_requires_identity_or_code() -> None:
    with pytest.raises(ValueError, match="repair_id or codes"):
        MechanicalRepairRevision(kind="mechanical_repair")

    repair = MechanicalRepairRevision(kind="mechanical_repair", codes=("refresh_handle",))
    assert repair.model_dump(mode="json") == {
        "kind": "mechanical_repair",
        "repair_id": None,
        "codes": ["refresh_handle"],
    }
