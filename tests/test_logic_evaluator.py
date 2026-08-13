from itertools import product
from typing import Any, cast

import pytest
from oracle.rob2_parallel import QIDS, cases, judgment, overall
from pydantic import ValidationError

from rob2_kit.logic import evaluate_domain, evaluate_overall
from rob2_kit.models import Judgment, sha256
from rob2_kit.packs import (
    MAINTAINER_POLICY_PACK,
    SCIENTIFIC_PACK,
    load_policy_pack,
    load_scientific_pack,
)


def test_pack_ids_wording_provenance_and_hashes():
    assert len(SCIENTIFIC_PACK.questions) == 22
    # Independently reviewed against the cited 22 August 2019 Boxes 4, 6, 8, 10 and 11.
    assert sha256(
        tuple((question.id, question.wording) for question in SCIENTIFIC_PACK.questions)
    ) == ("sha256:96ff2d1a649d6b40f40fe7fa73c3127c5eb1725e8392b8728f9d25f951338425")
    assert SCIENTIFIC_PACK.questions[16].wording.startswith("If N/PN/NI to 4.1 and 4.2")
    assert SCIENTIFIC_PACK.content_hash.startswith("sha256:")
    assert "not attributed to Cochrane" in MAINTAINER_POLICY_PACK.attribution
    assert MAINTAINER_POLICY_PACK.id != SCIENTIFIC_PACK.id
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
        if values.count("some_concerns") >= 2 and "high" not in values:
            for combined in (False, True):
                assert evaluate_overall(
                    judgments, combined_concerns=combined
                ).judgment.value == overall(list(values), combined)
        else:
            assert evaluate_overall(judgments).judgment.value == overall(list(values))


def test_corrected_domain_four_no_information_paths():
    assert (
        evaluate_domain(
            "domain:measurement",
            {
                "sq:measurement:method-inappropriate": "yes",
                "sq:measurement:differential": "probably_no",
            },
        ).judgment
        is Judgment.HIGH
    )
    assert (
        evaluate_domain(
            "domain:measurement",
            {
                "sq:measurement:method-inappropriate": "no_information",
                "sq:measurement:differential": "no",
                "sq:measurement:assessor-aware": "no",
            },
        ).judgment
        is Judgment.LOW
    )
    assert (
        evaluate_domain(
            "domain:measurement",
            {
                "sq:measurement:method-inappropriate": "no",
                "sq:measurement:differential": "no",
                "sq:measurement:assessor-aware": "no_information",
                "sq:measurement:influence-possible": "no",
            },
        ).judgment
        is Judgment.LOW
    )


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
