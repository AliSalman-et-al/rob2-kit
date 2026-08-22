from rob2_kit.evaluation.trace import TraceEvent, check_required_operations, check_trace


def test_trace_rejects_all_release_signatures():
    failures = check_trace(
        (
            TraceEvent("defect", "save", detail="ValidationError schema validation"),
            TraceEvent("defect", "save", detail="ValidationError schema validation"),
            TraceEvent("transition", status="invalid"),
            TraceEvent("claim", detail="Assessment completed", durable_status="pending"),
            TraceEvent("prose", detail="the model says assessed", durable_status="needs_input"),
        )
    )
    assert len(failures) == 6


def test_required_ae_clarification_precedes_acknowledged_terminal():
    terminal = TraceEvent("operation", "preapproval_terminal", "acknowledged")
    assert (
        check_required_operations(
            (TraceEvent("operation", "clarify_adverse_events", "completed"), terminal),
            (("clarify_adverse_events", "completed"),),
        )
        == ()
    )
    assert check_required_operations((terminal,), (("clarify_adverse_events", "completed"),))


def test_required_operations_ignores_non_operation_gate_spoofs():
    required = (("clarify_adverse_events", "completed"),)
    terminal = TraceEvent("operation", "preapproval_terminal", "acknowledged")
    for kind in ("prose", "claim", "transition"):
        spoof = TraceEvent(kind, "clarify_adverse_events", "completed")
        assert check_required_operations((spoof, terminal), required) == (
            "required operation is absent before preapproval terminal: "
            "clarify_adverse_events/completed",
        )

        spoof_terminal = TraceEvent(kind, "preapproval_terminal", "acknowledged")
        assert check_required_operations(
            (TraceEvent("operation", "clarify_adverse_events", "completed"), spoof_terminal),
            required,
        ) == ("required preapproval terminal is absent",)
