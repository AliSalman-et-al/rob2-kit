"""Expand official2019 Tables4/6/10/12/14, independent of runtime branch logic."""

import hashlib, itertools, json, pathlib, runpy, sys, collections
from rob2_kit.logic.evaluator import active_questions, evaluate_domain
from rob2_kit.packs import SCIENTIFIC_PACK

A = ("yes", "probably_yes", "probably_no", "no", "no_information")
Y = A[:2]
N = A[2:4]
U = A[4:]
NY = N + U
YU = Y + U
NA = (None,)
# IDs only from existing oracle; neither oracle judgments nor path generator used.
ids = runpy.run_path("tests/oracle/rob2_parallel.py")["QIDS"]
# Unlisted D1 N/PN sequence with adequate concealment and no imbalance uses
# Figure1 sequence-generation branch (Some concerns), alongside Table4.
rows = {
    "domain:randomization": [
        (Y + U, Y, NY, "low"),
        (N, Y, A, "some_concerns"),
        (Y + U, Y, Y, "some_concerns"),
        (A, U, NY, "some_concerns"),
        (A, U, Y, "high"),
        (A, N, A, "high"),
    ],
    "domain:missing": [
        (Y, NA, NA, NA, "low"),
        (NY, Y, NA, NA, "low"),
        (NY, N, N, NA, "low"),
        (NY, N, YU, N, "some_concerns"),
        (NY, N, YU, YU, "high"),
    ],
    "domain:measurement": [
        (NY, N, N, NA, NA, "low"),
        (NY, N, YU, N, NA, "low"),
        (NY, N, YU, YU, N, "some_concerns"),
        (NY, N, YU, YU, YU, "high"),
        (NY, U, N, NA, NA, "some_concerns"),
        (NY, U, YU, N, NA, "some_concerns"),
        (NY, U, YU, YU, N, "some_concerns"),
        (NY, U, YU, YU, YU, "high"),
        (Y, A, NA, NA, NA, "high"),
        (NY, Y, NA, NA, NA, "high"),
    ],
    "domain:selection": [
        (Y, N, N, "low"),
        (NY, N, N, "some_concerns"),
        (A, N, U, "some_concerns"),
        (A, U, N, "some_concerns"),
        (A, U, U, "some_concerns"),
        (A, Y, A, "high"),
        (A, NY, Y, "high"),
    ],
}
# Table6 part1 six rows; split awareness union to avoid duplicates.
part1 = [(N, N, NA, NA, NA, "low")]
for awareness in [(YU, A), (N, YU)]:
    for tail in [
        (N, NA, NA, "low"),
        (U, NA, NA, "some_concerns"),
        (Y, N, NA, "some_concerns"),
        (Y, YU, Y, "some_concerns"),
        (Y, YU, NY, "high"),
    ]:
        part1.append((*awareness, *tail))
part2 = [(Y, NA, "low"), (NY, N, "some_concerns"), (NY, YU, "high")]
rank = {"low": 0, "some_concerns": 1, "high": 2}
rows["domain:deviations"] = [
    (*p[:-1], *q[:-1], max((p[-1], q[-1]), key=rank.__getitem__)) for p in part1 for q in part2
]


# Box6/8/10 conditional wording, separately evaluated from table masks.
def expected_active(domain, v):
    if domain in ("domain:randomization", "domain:selection"):
        return [True] * 3
    if domain == "domain:deviations":
        c = v[0] in YU or v[1] in YU
        d = c and v[2] in Y
        e = d and v[3] in YU
        return [True, True, c, d, e, True, v[5] in NY]
    if domain == "domain:missing":
        b = v[0] in NY
        c = b and v[1] in N
        d = c and v[2] in YU
        return [True, b, c, d]
    b = v[0] in NY and v[1] in NY
    c = b and v[2] in YU
    d = c and v[3] in YU
    return [True, True, b, c, d]


standalone = runpy.run_path("scripts/verify_bundle.py")["_domain_judgment"]
result = {}
for domain, rs in rows.items():
    paths = {}
    duplicates = 0
    for row in rs:
        for v in itertools.product(*row[:-1]):
            if v in paths:
                assert paths[v] == row[-1]
                duplicates += 1
            paths[v] = row[-1]
    # Independent complete assignment expansion verifies row coverage, not just row consistency.
    complete = set()
    choices = [A[:4] if q == "sq:missing:evidence-unbiased" else A for q in ids[domain]]
    for full in itertools.product(*choices):
        mask = expected_active(domain, full)
        complete.add(tuple(x if on else None for x, on in zip(full, mask, strict=True)))
    assert complete == set(paths), (domain, "missing/extraneous table path")
    counts = collections.Counter()
    neg = 0
    for v, want in paths.items():
        a = {q: x for q, x in zip(ids[domain], v, strict=True) if x is not None}
        flags = expected_active(domain, v)
        assert [x is not None for x in v] == flags
        active = set(active_questions(a)) & set(ids[domain])
        assert active == set(a)
        assert evaluate_domain(domain, a).judgment.value == want
        assert standalone(domain, a) == want
        counts[want] += 1
        # Every forbidden active NA, every missing active answer, and every inactive
        # supplied value must be rejected; all five values included for inactive SQs.
        for q, x in zip(ids[domain], v, strict=True):
            probes = [{**a, q: "not_applicable"}] if x is not None else [{**a, q: z} for z in A]
            if x is not None:
                probes.append({k: z for k, z in a.items() if k != q})
            for probe in probes:
                try:
                    evaluate_domain(domain, probe)
                except ValueError:
                    neg += 1
                else:
                    raise AssertionError((domain, probe, "invalid path accepted"))
    result[domain] = {
        "unique_valid_active_paths": len(paths),
        "judgment_counts": dict(counts),
        "negative_controls_rejected": neg,
        "same_label_duplicate_expansions": duplicates,
    }
# Question3.2 explicitly has no NI option: invalid in all activated contexts.
for availability in NY:
    a = dict(zip(ids["domain:missing"][:2], (availability, "no_information"), strict=True))
    try:
        evaluate_domain("domain:missing", a)
    except ValueError as error:
        assert "answer is not allowed for sq:missing:evidence-unbiased" in str(error)
    else:
        raise AssertionError("3.2NI accepted")
source = pathlib.Path(sys.argv[2])
assert (
    hashlib.sha256(source.read_bytes()).hexdigest()
    == "a9e9c4fdc4be2d29b5c0a1a6b828e09f2014a34f6d5c302a532f6153ea0fd670"
), "Official PDF bytes differ; inspect before comparing"
receipt = {
    "official_url": "https://www.cochrane.de/sites/cochrane.de/files/uploads/RoB_2.0_guidance_2019.pdf",
    "official_pdf_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    "official_version": "22August2019",
    "source_locators": {
        "D1": "Box4 pp16–18;Table4/Figure1 p20",
        "D2": "Box6 pp28–29;Table6/Figure2 pp32–33, assignmenteffect only",
        "D3": "Box8 pp45–46;Table10/Figure4 pp47–48",
        "D4": "Box10 pp54–55;Table12/Figure5 p57",
        "D5": "Box11 pp62–65;Table14/Figure7 p67",
        "NA": "section1.1 p3: conditional-question NotApplicable; represented by omission in native typed API",
    },
    "table_expansion_results": result,
    "all_domain_judgments_and_activation_masks_match": True,
    "no_scientific_product_change": True,
    "reference_boundary": "Manual table-row expansion and separately transcribed conditional wording; imports oracle only for stable question IDs, not oracle logic/cases. NA omitted; explicit active NA rejected. This verifies mapping of supplied answers, not scientific evidence warrant or benchmark accuracy.",
}
pathlib.Path(sys.argv[1]).write_text(json.dumps(receipt, indent=2) + "\n")
print(json.dumps(result, indent=2))
