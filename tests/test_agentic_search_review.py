from typing import Any

import pytest

from rob2_kit.application.trials import _domain_attribution, _review_payload
from rob2_kit.packs import SCIENTIFIC_PACK
from rob2_kit.workflow_models import MechanicalRepairRevision


def _records(basis: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    return {
        f"trial:{domain.id}": {
            "identity": f"checkpoint-{index}",
            **({"revision_basis": basis} if basis is not None else {}),
        }
        for index, domain in enumerate(SCIENTIFIC_PACK.domains)
    }


@pytest.mark.parametrize(
    ("basis", "expected"),
    [
        (None, "unchanged"),
        ({"kind": "self_correction", "rationale": "Corrected interpretation."}, "self_correction"),
        (
            {"kind": "new_evidence", "evidence": "sha256:" + "a" * 64, "rationale": "New source."},
            "new_evidence",
        ),
        (
            {"kind": "mechanical_repair", "codes": ["refresh_handle"]},
            "mechanical_repair",
        ),
    ],
)
def test_review_attributes_each_current_domain_from_stored_revision_basis(
    basis: dict[str, Any] | None, expected: str
) -> None:
    summary = _domain_attribution({"domain_records": _records(basis)}, "trial")

    assert [item["attribution"] for item in summary] == [expected] * len(SCIENTIFIC_PACK.domains)
    assert all(item["checkpoint_identity"].startswith("checkpoint-") for item in summary)


def test_review_payload_retains_explicit_attribution_summary() -> None:
    state = {
        "proposal": {"payload": {"results": [{"trial_id": "trial", "kind": "assessable"}]}},
        "domain_records": _records({"kind": "mechanical_repair", "repair_id": "repair-1"}),
    }

    payload = _review_payload(state, "trial", "assessed", None, [])

    assert payload["domain_attribution"][0]["attribution"] == "mechanical_repair"
    assert payload["domain_attribution"][0]["revision_basis"] == {
        "kind": "mechanical_repair",
        "repair_id": "repair-1",
    }


def test_mechanical_repair_requires_identity_or_code() -> None:
    with pytest.raises(ValueError, match="repair_id or codes"):
        MechanicalRepairRevision(kind="mechanical_repair")

    repair = MechanicalRepairRevision(kind="mechanical_repair", codes=("refresh_handle",))
    assert repair.model_dump(mode="json") == {
        "kind": "mechanical_repair",
        "repair_id": None,
        "codes": ["refresh_handle"],
    }
