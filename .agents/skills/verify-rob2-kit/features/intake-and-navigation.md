# Intake and source navigation

The host prepares a batch from the trial folders under `input/`. Each source is
captured by its hash. The host then reads pages, searches and renders figures,
and selects passages as evidence handles that later answers cite.

## Sub-features

- `prepare` registers the trials, captures the sources and resolves roles from `sources.toml`.
- `list-sources` returns each trial's sources with their `id`, `role` and `label`.
- `read` returns numbered page text through `read_pages` (by page or by window).
- `search` covers `search_sources` (modes `all` and `phrase`) and `search_sources_batch`. A zero-hit receipt counts as an absence search.
- `render` returns a PNG and a delivery receipt from `render_page`. `select_visual_evidence` turns that receipt into a handle.
- `cite` turns a literal quote or line range into a handle through `select_text_evidence`.
- `guidance` covers `read_guidance` for the skill documents and `calculate_arithmetic` for checked arithmetic.

## How to get to it (user POV)

- The host calls `prepare_batch` with the researcher's outcome. The skill does this first.
- The host calls the navigation tools while it builds a proposal or answers questions.

## Driving it with the e2e Agent

Preconditions: `trial.build(ws)`, and optionally `trial.build_sparse(ws)`, then `agent = Agent(ws)`.

- **Prepare.** Run `agent.prepare("recurrent stroke within 12 months")`. `data.trials` lists `prevent-tia` with its `main_article`, `protocol` and registry sources.
- **Read gate.** `agent.next_action()["operation"] == "read_pages"` with `windows`. Run `agent.read_required()`, which reads them all.
- **Search.** Run `agent.ok("search_sources", {"trial_id": "prevent-tia", "query": "interactive web response", "mode": "phrase"})`. The first hit is on page 1.
- **Absence.** A batch request for `"sealed opaque envelopes"` (phrase) returns `hits == []` together with a `search_receipt`.
- **Render.** Run `agent.ok("render_page", {..., "page": 2})`, then pass its `data.delivery_receipt` to `select_visual_evidence` with a transcription. The result has `data.evidence.handle`.
- **Cite.** Run `agent.cite_lines("main_article", 1, "randomly assigned (1:1)")`. The handle starts with `eh_`.

## Gotchas

- `read_pages` accepts at most 10 pages per call.
- PDF text breaks phrases across lines, so `cite` with a literal quote can miss. Use `cite_lines`.
- `sources.toml` rejects unknown keys. Without a `[registry]` table, the trial's own NCT number in the main report triggers a live ClinicalTrials.gov lookup. The synthetic trials avoid this with a replay.
