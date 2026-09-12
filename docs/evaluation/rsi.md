# Recursive assessment improvement

Use this development loop for one trial and one approved Result at a time. It is
diagnostic work, separate from release qualification and its held-out score.
The [evaluation contract](README.md) defines the observation limits.

1. Rank assessed rows by **D1–D5** agreement, then choose a failure with a
   testable mechanism. Keep all outcomes from the same trial in one development
   or holdout partition. An overall judgment is not the optimization target.
2. Freeze the prompt, dossier bytes, model/version, reasoning effort, tool and
   skill revision, and evaluation rule. Start an empty run directory. Use
   `scripts/run_rsi_case.py` with `--input`, `--prompt`, `--run-dir`, and
   `--phase 1`. The directory contains its own copied input, exported skill,
    Codex session store, metadata, full CLI JSONL and stderr. The runner removes
    the temporary auth copy after each phase. Keep raw traces restricted because
    they contain source text and host-visible agent messages or justifications.
3. At Proposal Review, inspect the exact Result mapping. Approve only the
   intended source-reported Result through the supported researcher gate. For
   subsequent phases, rerun the script with the same run directory, `--phase N`,
   `--session` from the prior JSONL, and a file containing `Continue.`. The runner
   checks the isolated `rob2 status` before starting a paid continuation and stops
   if the researcher Proposal Review is still pending; acknowledge that exact
   Review with the researcher-only `rob2 review` command first. Keep the full
   Codex session rollout with the phase traces: it retains encrypted reasoning
   records and exposed agent messages or justifications, while the phase JSONL
   alone is not the complete host rollout. Neither artifact exposes readable
   model reasoning or a complete raw chain of thought. Use a new run directory
   for the intervention; never reuse an assessment workspace.
4. Audit the actual host-visible trace, committed Evidence, question premises,
   and final bundle. Distinguish retrieved, surfaced, delivered, selected,
   cited, and premise-supporting material. For a Codex host probe, unwrap one
   `structured_content`/`structuredContent` receipt (or parse its one JSON text
   fallback) before rendering it. Set `functions.exec` `max_output_tokens` high
   enough for the complete object and retry the same call when the host reports
   `Warning: truncated output`; record the measured structured/text byte sizes.
   Keep `head`, `result`, `questions`, `comparison_cards`, Evidence, and
   recovery fields together. A tool receipt does not establish model attention.
   Compare the five domains and class-specific errors against the reference;
   record scientifically defensible disagreements separately.
5. Make one generalized change supported by a bounded mechanism test. Rerun
   the same frozen case with the same budget. Check newly broken controls as
   well as recovered failures. A one-draw label change is a diagnostic signal,
   not evidence of population-level accuracy gain.
6. Commit and push a reviewed change only after focused tests and direct
   artifact verification. Keep its issue open if the trial-separated,
   multi-model promotion gate remains untested. Move to the next failure case.
   After three completed cycles, create one focused pull request and squash
   merge it into `main` once checks and review pass.

The first three cycles may share a branch, but each intervention needs its own
fresh assessment workspace and trace. If corpus bytes, registry capture, Result
mapping, or host behavior differ, record that difference and do not attribute
the resulting score delta solely to the kit. Reserve untouched trials and
document families for independent evaluation. Avoid tuning a rule to a trial
name, reference label, or one model's preferred phrasing.
