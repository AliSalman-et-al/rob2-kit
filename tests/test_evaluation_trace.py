from rob2_kit.evaluation.trace import TraceEvent, check_trace


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
