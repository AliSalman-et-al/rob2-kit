"""Manual transcription of Tables 3-6, 9-10, 11-14 and overall Table 1."""

ANSWERS = ("yes", "probably_yes", "probably_no", "no", "no_information")
YES = {"yes", "probably_yes"}
NO = {"probably_no", "no"}
NO_U = NO | {"no_information"}

QIDS = {
    "domain:randomization": (
        "sq:randomization:sequence",
        "sq:randomization:concealment",
        "sq:randomization:baseline-imbalance",
    ),
    "domain:deviations": (
        "sq:deviations:participants-aware",
        "sq:deviations:personnel-aware",
        "sq:deviations:context-deviations",
        "sq:deviations:affected-outcome",
        "sq:deviations:balanced",
        "sq:deviations:appropriate-analysis",
        "sq:deviations:substantial-impact",
    ),
    "domain:missing": (
        "sq:missing:data-available",
        "sq:missing:evidence-unbiased",
        "sq:missing:true-value-dependent",
        "sq:missing:likely-dependent",
    ),
    "domain:measurement": (
        "sq:measurement:method-inappropriate",
        "sq:measurement:differential",
        "sq:measurement:assessor-aware",
        "sq:measurement:influence-possible",
        "sq:measurement:influence-likely",
    ),
    "domain:selection": (
        "sq:selection:prespecified-analysis",
        "sq:selection:multiple-measurements",
        "sq:selection:multiple-analyses",
    ),
}


def active(a):
    return {
        **{q: True for q in QIDS["domain:randomization"] + QIDS["domain:selection"]},
        "sq:deviations:participants-aware": True,
        "sq:deviations:personnel-aware": True,
        "sq:deviations:context-deviations": a.get("sq:deviations:participants-aware")
        in YES | {"no_information"}
        or a.get("sq:deviations:personnel-aware") in YES | {"no_information"},
        "sq:deviations:affected-outcome": a.get("sq:deviations:context-deviations") in YES,
        "sq:deviations:balanced": a.get("sq:deviations:affected-outcome")
        in YES | {"no_information"},
        "sq:deviations:appropriate-analysis": True,
        "sq:deviations:substantial-impact": a.get("sq:deviations:appropriate-analysis") in NO_U,
        "sq:missing:data-available": True,
        "sq:missing:evidence-unbiased": a.get("sq:missing:data-available") in NO_U,
        "sq:missing:true-value-dependent": a.get("sq:missing:evidence-unbiased") in NO,
        "sq:missing:likely-dependent": a.get("sq:missing:true-value-dependent")
        in YES | {"no_information"},
        "sq:measurement:method-inappropriate": True,
        "sq:measurement:differential": True,
        "sq:measurement:assessor-aware": a.get("sq:measurement:method-inappropriate") in NO_U
        and a.get("sq:measurement:differential") in NO_U,
        "sq:measurement:influence-possible": a.get("sq:measurement:assessor-aware")
        in YES | {"no_information"},
        "sq:measurement:influence-likely": a.get("sq:measurement:influence-possible")
        in YES | {"no_information"},
    }


def cases(domain):
    ids = QIDS[domain]

    def visit(index, values):
        if index == len(ids):
            yield values
            return
        q = ids[index]
        if not active(values)[q]:
            yield from visit(index + 1, values)
            return
        choices = ANSWERS[:4] if q == "sq:missing:evidence-unbiased" else ANSWERS
        for value in choices:
            yield from visit(index + 1, values | {q: value})

    yield from visit(0, {})


def judgment(domain, a):
    if domain == "domain:randomization":
        if a["sq:randomization:concealment"] in NO or (
            a["sq:randomization:concealment"] == "no_information"
            and a["sq:randomization:baseline-imbalance"] in YES
        ):
            return "high"
        return (
            "some_concerns"
            if a["sq:randomization:sequence"] in NO
            or a["sq:randomization:concealment"] == "no_information"
            or a["sq:randomization:baseline-imbalance"] in YES
            else "low"
        )
    if domain == "domain:deviations":
        if (
            a.get("sq:deviations:context-deviations") in YES
            and a.get("sq:deviations:affected-outcome") in YES | {"no_information"}
            and a.get("sq:deviations:balanced") in NO_U
        ):
            return "high"
        if a["sq:deviations:appropriate-analysis"] in NO_U and a.get(
            "sq:deviations:substantial-impact"
        ) in YES | {"no_information"}:
            return "high"
        return (
            "some_concerns"
            if a.get("sq:deviations:context-deviations") == "no_information"
            or a.get("sq:deviations:affected-outcome") in NO
            or a.get("sq:deviations:balanced") in YES
            or a.get("sq:deviations:substantial-impact") in NO
            else "low"
        )
    if domain == "domain:missing":
        if (
            a["sq:missing:data-available"] in YES
            or a.get("sq:missing:evidence-unbiased") in YES
            or a.get("sq:missing:true-value-dependent") in NO
        ):
            return "low"
        return (
            "high"
            if a.get("sq:missing:likely-dependent") in YES | {"no_information"}
            else "some_concerns"
        )
    if domain == "domain:measurement":
        if (
            a["sq:measurement:method-inappropriate"] in YES
            or a["sq:measurement:differential"] in YES
            or a.get("sq:measurement:influence-likely") in YES | {"no_information"}
        ):
            return "high"
        return (
            "some_concerns"
            if a["sq:measurement:differential"] == "no_information"
            or a.get("sq:measurement:influence-likely") in NO
            else "low"
        )
    if a["sq:selection:multiple-measurements"] in YES or a["sq:selection:multiple-analyses"] in YES:
        return "high"
    return (
        "some_concerns"
        if a["sq:selection:prespecified-analysis"] in NO_U
        or a["sq:selection:multiple-measurements"] == "no_information"
        or a["sq:selection:multiple-analyses"] == "no_information"
        else "low"
    )


def overall(values, combined=None):
    if "high" in values:
        return "high"
    concerns = values.count("some_concerns")
    if concerns >= 2:
        return "high" if combined else "some_concerns"
    return "some_concerns" if concerns else "low"
