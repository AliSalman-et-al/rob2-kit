from itertools import product
from typing import Any, cast

import pytest
from oracle.rob2_parallel import QIDS, cases, judgment
from pydantic import ValidationError

from rob2_kit.logic import evaluate_domain, evaluate_overall
from rob2_kit.packs import (
    MAINTAINER_POLICY_PACK,
    SCIENTIFIC_PACK,
    load_policy_pack,
    load_scientific_pack,
)


def test_packs_round_trip_and_reject_tampering():
    assert load_scientific_pack(SCIENTIFIC_PACK.model_dump(mode="json")) == SCIENTIFIC_PACK
    assert (
        load_policy_pack(MAINTAINER_POLICY_PACK.model_dump(mode="json")) == MAINTAINER_POLICY_PACK
    )
    with pytest.raises(ValueError, match="hash"):
        load_scientific_pack({**SCIENTIFIC_PACK.model_dump(mode="json"), "version": "tampered"})
    with pytest.raises(ValueError, match="hash"):
        load_policy_pack({**MAINTAINER_POLICY_PACK.model_dump(mode="json"), "version": "tampered"})


def test_policy_lexical_seeds_are_deeply_immutable_and_deterministic():
    assert MAINTAINER_POLICY_PACK.seeds_for("randomization") == ("random", "allocation", "conceal")
    assert MAINTAINER_POLICY_PACK.source_priority == (
        "main_article",
        "registry",
        "supplement",
        "sap",
        "protocol",
        "other",
    )
    with pytest.raises(TypeError):
        cast(Any, MAINTAINER_POLICY_PACK.lexical_seeds)[0] = MAINTAINER_POLICY_PACK.lexical_seeds[0]
    with pytest.raises(ValidationError):
        cast(Any, MAINTAINER_POLICY_PACK.lexical_seeds[0]).terms += ("changed",)


@pytest.mark.parametrize("domain", tuple(QIDS))
def test_all_admissible_domain_paths_against_independent_oracle(domain):
    paths = list(cases(domain))
    assert paths
    for answers in paths:
        actual = evaluate_domain(domain, answers)
        assert actual.judgment.value == judgment(domain, answers)
        assert actual.trace


def test_all_overall_combinations_against_independent_oracle():
    domain_ids = tuple(QIDS)
    for values in product(("low", "some_concerns", "high"), repeat=5):
        judgments = dict(zip(domain_ids, values, strict=True))
        if "high" in values:
            expected = "high"
        elif "some_concerns" in values:
            expected = "some_concerns"
        else:
            expected = "low"
        assert evaluate_overall(judgments).judgment.value == expected


def test_rejects_unknown_inactive_and_missing_answers():
    with pytest.raises(ValueError, match="unknown signalling answer"):
        evaluate_domain("domain:randomization", {"sq:randomization:sequence": "wat"})
    with pytest.raises(ValueError, match="missing"):
        evaluate_domain("domain:measurement", {"sq:measurement:method-inappropriate": "no"})
    with pytest.raises(ValueError, match="unknown signalling question"):
        evaluate_domain(
            "domain:randomization",
            {
                "sq:randomization:sequence": "yes",
                "sq:randomization:concealment": "yes",
                "sq:randomization:baseline-imbalance": "no",
                "sq:not-real": "yes",
            },
        )


def test_allowed_answer_restrictions_still_apply_to_active_questions():
    with pytest.raises(ValueError):
        evaluate_domain(
            "domain:missing",
            {
                "sq:missing:data-available": "no",
                "sq:missing:evidence-unbiased": "no_information",
            },
        )
