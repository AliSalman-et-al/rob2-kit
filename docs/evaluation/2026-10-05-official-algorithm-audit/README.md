# Official2019 assignment-effect algorithm audit

No deterministic D1–D5 mismatch was found. Existing coverage already includes exhaustive admissible paths against a manual oracle, answer-option validation, justified domain overrides, and qualified overall confidence with historical replay. No new product logic, fixture collection or test framework was added.

This audit reread the official22August2019 source and independently expanded Table4/Figure1(D1), Table6(D2 assignment effect), Table10(D3), Table12(D4), and Table14(D5), plus the conditional wording in Boxes6/8/10. The [source PDF](https://www.cochrane.de/sites/cochrane.de/files/uploads/RoB_2.0_guidance_2019.pdf) SHA256 is `a9e9c4fdc4be2d29b5c0a1a6b828e09f2014a34f6d5c302a532f6153ea0fd670`. Figure1 also covers the D1 nonrandom-sequence branch that Table4’s printed rows leave incomplete.

| Domain | Unique valid active paths | Invalid submissions rejected |
|---|---:|---:|
| D1 |125|750|
| D2 |13,277|201,886|
| D3 |110|970|
| D4 |493|5,344|
| D5 |125|750|
| Total |14,130|209,700|

Every table-expanded path matched runtime and standalone proposed judgments. A separate enumeration over all answer assignments and independently transcribed activation predicates verified complete path coverage and exact active-question masks. Negative controls exercised missing active answers, all five values supplied to inactive questions, and explicit NA supplied to active questions. Additional probes rejected NI for3.2, whose official response options exclude NI. Official conditional NA is represented by omission in this native typed interface; it is not an extra answer that can bypass activation.

NI remains question-specific. NI sequence generation with adequate concealment and no imbalance can yield D1Low. NI substantial analysis impact in D2.7, NI likely dependence in D3.4, and NI likely assessment influence in D4.5 can yield High. These default mappings do not establish factual dependence or bias. The separate justified domain override remains intact; no label was changed to make uncertainty comforting. Overall Table1’s qualified confidence rule and historical replay semantics remain intact.

Reproduce from the repository root after downloading the pinned official PDF:

```bash
PYTHONPATH=src:tests python docs/evaluation/2026-10-05-official-algorithm-audit/verify_tables.py /tmp/algorithm-receipt.json /path/to/RoB_2.0_guidance_2019.pdf
```

The script imports existing oracle data only for stable question IDs, never its path generator or judgment logic. Reference rows and activation rules were transcribed from the official source. [Verification receipt](verification.json) records exact locators and counts. This is an implementation-agent verification, not independent human certification, source-warrant validation, benchmark accuracy or evidence of model improvement. No paid evaluation or full benchmark was run.

Existing evaluator, conditional-overall and domain-adjudication suites: **41passed in65.99seconds**. Published reproduction script was rerun successfully against the pinned PDF, with identical counts.

Independent review reproduced the paths, invalid controls and bound source/script/product hashes and returned scopedGO. It did not rerun the41test suite. The additional3.2NI probes now supply only3.1and3.2in each of three activating3.1states and assert the specific forbidden-answer error, correcting a control confound without changing scientific logic.
