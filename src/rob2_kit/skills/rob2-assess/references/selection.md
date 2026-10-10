# Domain 5: bias in selection of the reported result

Source: RoB 2 full guidance, section 8 and Box 11. The complete official text is
returned by `get_domain_context`.

This domain asks whether the reported result was chosen, on the basis of its
results, from several measurements or analyses of the outcome. It does not
cover outcomes that were not reported at all.

Distinguish the **outcome domain** (for example depression), an **outcome
measurement** (a scale at a time point) and an **outcome analysis** (for
example an adjusted difference in change scores). Only measurements and
analyses eligible for the review count as alternatives. Unless the researcher
restricted eligibility, judge eligibility from the requested outcome, not from
the scale, time point or analysis the selected result happens to use.

## Read first: the analysis intentions

Find the trial's pre-specified intentions and their dates in the captured
Sources: a protocol or design paper, a statistical analysis plan (it may be a
section of a protocol or supplement), and the trial registry record. Compare
them with the methods and results of the report. Then compare what the methods
section says was measured and analysed with what the results report, and
compare across all reports of the trial.

The Domain 5 context lists the registry record's registered outcomes (with
time frames) in `registry_outcomes` and its dates (first submitted, first
posted, start, primary completion, last update) in `registration`; each has a
`recovery` window to read and cite. ClinicalTrials.gov's API returns the current record, not earlier
versions: outcome wording first registered before enrolment and unchanged in
the report supports prespecification of the measurement, but the current
record alone cannot show what an earlier version said or when an analysis was
fixed. Document upload and approval dates show when a document was filed, not
when the plan was finalized relative to unblinding.

When nothing pre-specified is available, section 8.3.2 still lets you infer
selection from the report: unusual subscale aggregation, primary or secondary
designations that differ between reports, several adjusted analyses with only
one reported, unusual categorization of continuous measures, different analysed
samples across reports, or unusual composites.

## 5.1 (`sq:selection:prespecified-analysis`) Were the data analysed in accordance with a pre-specified plan finalized before unblinded outcome data were available?

- **Yes / Probably yes:** a protocol, SAP or registry entry specifies this
  outcome measurement and analysis, and was dated before unblinded outcome data
  were available (for example registered before enrolment finished, or an SAP
  finalized before database lock in a blinded trial), and the report follows it.
  Changes made before unblinding, or clearly unrelated to the results, do not
  raise concerns. Amendments to other parts of the plan do not affect this
  Result.
- Compare the report with the plan versions in date order. If a version dated
  before unblinded data were available already specified this measurement and
  analysis, and the report follows it, a later version does not make 5.1 No.
  Unblinded data seen only by an independent data monitoring committee, for
  example at an interim analysis, are not available to the trial investigators
  (section 8.3.1).
- **No / Probably no:** the plan for this measurement or analysis changed after
  unblinded data were available, or the report departs from the plan without a
  result-independent reason.
- **No information:** no pre-specified intentions for this Result are available
  in sufficient detail, or their timing cannot be placed relative to unblinding.

## 5.2 (`sq:selection:multiple-measurements`) Is the result likely to have been selected, on the basis of the results, from multiple eligible outcome measurements (scales, definitions, time points)?

- **Yes / Probably yes:** clear evidence (usually from a protocol or SAP) that
  the outcome domain was measured in several eligible ways but only one or a
  subset is fully reported without justification, and the reported one was
  likely chosen for its results.
- **No / Probably no:** all eligible reported results correspond to all
  intended measurements; or there is only one way to measure the outcome
  domain (for example all-cause mortality at the planned follow-up); or
  differences between reports are explained for reasons unrelated to the
  results.
- **No information:** intentions are unavailable or too vague, and the outcome
  domain could have been measured in more than one way.

## 5.3 (`sq:selection:multiple-analyses`) Is the result likely to have been selected, on the basis of the results, from multiple eligible analyses?

Multiple analyses include adjusted versus unadjusted models; final values,
change scores or ANCOVA; transformations; different composite definitions;
different cut-points; different covariate sets; and different missing-data
strategies.

- **Yes / Probably yes:** clear evidence that a measurement was analysed in
  several eligible ways but only one or a subset is fully reported without
  justification, and the reported one was likely chosen for its results.
- **No / Probably no:** all eligible reported results correspond to all
  intended analyses; or there is only one possible analysis; or differences
  between reports are explained for reasons unrelated to the results.
- **No information:** intentions are unavailable or too vague, and more than
  one analysis was possible.

Reporting several analyses (for example a pre-specified primary analysis and
sensitivity analyses that agree) is evidence against selection, not for it.

## Algorithm

- **High:** 5.2 Yes/Probably yes; or 5.3 Yes/Probably yes.
- **Some concerns:** 5.1 No/Probably no/No information; or 5.2 No information;
  or 5.3 No information.
- **Low:** otherwise (5.1 Yes/Probably yes and 5.2, 5.3 No/Probably no).

## Add an explicitly referenced protocol or SAP

If a captured Source cites a public protocol or SAP PDF by DOI or URL (or a
ClinicalTrials.gov document filename in the registry record), you can add it
during an approved open Trial:

1. Call `acquire_companion_source(reference={...}, expected_revision=...)`. Put
   every reference field inside `reference`: the native `source_id`, `page`,
   `citation` (a contiguous literal quote from that page containing the DOI,
   URL or filename, without line numbers or added prose), `linkage_rationale`,
   `requested_role` (`protocol` or `sap`), `locator_kind` (`url` or `doi`),
   `locator`, and optional `registry_id`. For a registry document, the locator
   is `https://cdn.clinicaltrials.gov/large-docs/<last two digits>/<NCT>/<filename>`.
2. If a candidate is staged, call `admit_companion_source(trial_id=...,
   candidate_identity=..., expected_revision=...)`. The PDF and its provenance
   become new Sources in the same assessment.
3. Read the new Sources with `read_pages` before using them, and check that the
   document covers this trial, comparison and outcome, and which version it is.

Only ClinicalTrials.gov CDN, PLOS and PMC PDFs are fetched; other references stay
unresolved. Admission never changes the approved Result. If the new document
shows the approved Result was mapped wrongly, report the conflict rather than
assessing a different Result. Revise any affected saved Domain through its
explicit revision basis and repeat the Trial review.

Use [Build a Domain answer](evidence.md#build-a-domain-answer) for the
submission shape.
