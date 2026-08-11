from inspect import signature
from typing import get_type_hints

from rob2_kit.application.contracts import (
    RUN_OPERATION_CONTRACTS,
    RUN_OPERATION_NAMES,
    OperationResponse,
    RunOperation,
)
from rob2_kit.application.run_engine import RunEngine
from rob2_kit.domain.revisions import FrozenModel

EXPECTED_OPERATIONS = (
    "prepare_run",
    "run_status",
    "continue_run",
    "reprioritize_results",
    "withdraw_result",
    "reopen_result",
    "get_work_context",
    "submit_run_proposal",
    "submit_proposal_discovery_review",
    "submit_result_mapping_review",
    "confirm_run_definition",
    "search_evidence",
    "read_evidence",
    "inspect_visual_candidate",
    "submit_source_role_review",
    "submit_result_resolution",
    "submit_domain_evidence",
    "submit_evidence_review",
    "submit_domain_answers",
    "correct_domain_answers",
)


def test_fixed_run_engine_surface_has_twenty_one_to_one_typed_operations() -> None:
    assert RUN_OPERATION_NAMES == EXPECTED_OPERATIONS
    assert tuple(contract.operation.value for contract in RUN_OPERATION_CONTRACTS) == (
        EXPECTED_OPERATIONS
    )
    assert len(set(RUN_OPERATION_NAMES)) == 20

    for contract in RUN_OPERATION_CONTRACTS:
        method = getattr(RunEngine, contract.operation.value)
        hints = get_type_hints(method)
        parameters = tuple(signature(method).parameters)

        assert parameters == ("self", "request")
        assert issubclass(contract.request_type, FrozenModel)
        assert issubclass(contract.response_type, OperationResponse)
        assert hints["request"] is contract.request_type
        assert hints["return"] is contract.response_type
        assert contract.expected_conditions


def test_run_engine_has_no_generic_public_dispatch_method() -> None:
    public_methods = {
        name
        for name, value in RunEngine.__dict__.items()
        if callable(value) and not name.startswith("_")
    }

    assert public_methods == {operation.value for operation in RunOperation}
    assert "call" not in public_methods
    assert "dispatch" not in public_methods
