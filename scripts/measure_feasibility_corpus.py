"""Measure private RoB 2 feasibility PDFs without exporting their content.

The JSON output contains aggregate and per-document operational metrics only.
It deliberately excludes extracted text, filenames below the trial level, and
the provisional judgment CSVs.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import re
import sqlite3
import statistics
import time
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from liteparse import LiteParse

PROBES = {
    "randomization": '"random allocation" OR random* OR allocat*',
    "allocation_concealment": '"allocation concealment" OR conceal* OR envelope*',
    "baseline": '"baseline characteristics" OR baseline',
    "deviations_blinding": 'blind* OR mask* OR deviation* OR crossover',
    "analysis_population": '"intention to treat" OR "intention-to-treat" OR '
    '"full analysis set" OR "per-protocol"',
    "missing_outcomes": '"lost to follow-up" OR withdraw* OR missing OR censor*',
    "outcome_measurement": '"outcome assessor" OR adjudicat* OR "independent review"',
    "prespecification": 'prespecif* OR protocol OR "statistical analysis plan"',
    "multiple_analyses": '"multiple testing" OR multiplicity OR "sensitivity analysis"',
    "participant_flow": 'CONSORT OR "participant flow" OR "flow diagram"',
    "adverse_events": '"adverse events" OR "serious adverse" OR toxic*',
}


def percentile(values: Sequence[int | float], probability: float) -> float:
    if not values:
        return 0
    ordered = sorted(values)
    index = (len(ordered) - 1) * probability
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return float(ordered[lower])
    return float(
        ordered[lower] * (upper - index) + ordered[upper] * (index - lower)
    )


def distribution(values: Sequence[int | float]) -> dict[str, float]:
    return {
        "min": float(min(values, default=0)),
        "median": float(statistics.median(values)) if values else 0,
        "p90": percentile(values, 0.90),
        "p95": percentile(values, 0.95),
        "p99": percentile(values, 0.99),
        "max": float(max(values, default=0)),
    }


def trial_label(pdf: Path, corpus_root: Path) -> tuple[str, str]:
    relative = pdf.relative_to(corpus_root / "sources")
    return (
        relative.parts[0],
        "primary_report" if relative.parts[1] == "primary" else "supporting_source",
    )


def canonical_units(markdown: str, fallback_text: str) -> list[str]:
    source = markdown.strip() or fallback_text.strip()
    blocks = re.split(r"\n\s*\n+", source)
    units = [re.sub(r"\s+", " ", block).strip() for block in blocks]
    return [unit for unit in units if len(unit) >= 20]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--corpus-root", type=Path, default=Path("eval/reference")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("tmp/feasibility-calibration.json")
    )
    parser.add_argument(
        "--ocr-primary",
        action="store_true",
        help="Benchmark targeted OCR on flagged primary-report pages.",
    )
    args = parser.parse_args()

    corpus_root = args.corpus_root.resolve()
    pdfs = sorted((corpus_root / "sources").rglob("*.pdf"))
    liteparse = LiteParse(
        ocr_enabled=False,
        include_complexity=True,
        output_format="markdown",
        quiet=True,
    )

    connection = sqlite3.connect(":memory:")
    connection.execute(
        "CREATE VIRTUAL TABLE units USING fts5("
        "trial UNINDEXED, role UNINDEXED, document_id UNINDEXED, "
        "page UNINDEXED, text, tokenize='porter unicode61')"
    )

    documents: list[dict[str, Any]] = []
    unit_lengths: list[int] = []
    page_lengths: list[int] = []
    page_lengths_by_role: dict[str, list[int]] = {
        "primary_report": [],
        "supporting_source": [],
    }
    needs_ocr_lengths_by_role: dict[str, list[int]] = {
        "primary_report": [],
        "supporting_source": [],
    }
    needs_ocr_reason_sets: Counter[str] = Counter()
    complexity_reasons: Counter[str] = Counter()
    layout_reasons: Counter[str] = Counter()
    targeted_ocr: list[dict[str, Any]] = []
    start_all = time.perf_counter()

    for pdf in pdfs:
        label, role = trial_label(pdf, corpus_root)
        document_id = hashlib.sha256(pdf.read_bytes()).hexdigest()[:16]
        started = time.perf_counter()
        result = liteparse.parse(pdf)
        elapsed = time.perf_counter() - started

        needs_ocr_pages: list[int] = []
        garbled_pages: list[int] = []
        complex_pages: list[int] = []
        table_pages: list[int] = []
        figure_pages: list[int] = []
        blank_pages: list[int] = []

        for page in result.pages:
            text_length = len(page.text.strip())
            page_lengths.append(text_length)
            page_lengths_by_role[role].append(text_length)
            if text_length == 0:
                blank_pages.append(page.page_num)

            complexity = page.complexity
            if complexity:
                if complexity.needs_ocr:
                    needs_ocr_pages.append(page.page_num)
                    needs_ocr_lengths_by_role[role].append(text_length)
                    needs_ocr_reason_sets[
                        "+".join(sorted(complexity.reasons)) or "(none)"
                    ] += 1
                if complexity.is_garbled:
                    garbled_pages.append(page.page_num)
                complexity_reasons.update(complexity.reasons)
                layout = complexity.layout
                if layout is not None:
                    if layout.is_complex:
                        complex_pages.append(page.page_num)
                    if layout.ruled_table_count or layout.text_table_run_count:
                        table_pages.append(page.page_num)
                    if layout.figure_count:
                        figure_pages.append(page.page_num)
                    layout_reasons.update(layout.reasons)

            for unit in canonical_units(page.markdown, page.text):
                unit_lengths.append(len(unit))
                connection.execute(
                    "INSERT INTO units(trial, role, document_id, page, text) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (label, role, document_id, page.page_num, unit),
                )

        documents.append(
            {
                "trial": label,
                "role": role,
                "document_id": document_id,
                "bytes": pdf.stat().st_size,
                "pages": len(result.pages),
                "parse_seconds": round(elapsed, 3),
                "needs_ocr_pages": needs_ocr_pages,
                "garbled_pages": garbled_pages,
                "complex_pages": complex_pages,
                "table_signal_pages": table_pages,
                "figure_signal_pages": figure_pages,
                "blank_pages": blank_pages,
            }
        )

        if args.ocr_primary and role == "primary_report" and needs_ocr_pages:
            before_by_page = {
                page.page_num: len(page.text.strip())
                for page in result.pages
                if page.page_num in needs_ocr_pages
            }
            ocr_started = time.perf_counter()
            ocr_result = LiteParse(
                ocr_enabled=True,
                include_complexity=True,
                output_format="markdown",
                target_pages=",".join(str(page) for page in needs_ocr_pages),
                quiet=True,
            ).parse(pdf)
            targeted_ocr.append(
                {
                    "trial": label,
                    "pages": needs_ocr_pages,
                    "seconds": round(time.perf_counter() - ocr_started, 3),
                    "characters_before": sum(before_by_page.values()),
                    "characters_after": sum(
                        len(page.text.strip()) for page in ocr_result.pages
                    ),
                    "pages_still_flagged": [
                        page.page_num
                        for page in ocr_result.pages
                        if page.complexity and page.complexity.needs_ocr
                    ],
                }
            )

    connection.commit()
    probe_results: dict[str, Any] = {}
    for name, query in PROBES.items():
        rows = connection.execute(
            "SELECT trial, role, count(*) FROM units "
            "WHERE units MATCH ? GROUP BY trial, role ORDER BY trial, role",
            (query,),
        ).fetchall()
        hits_by_trial = Counter()
        primary_hits_by_trial = Counter()
        for trial, role, count in rows:
            hits_by_trial[trial] += count
            if role == "primary_report":
                primary_hits_by_trial[trial] += count
        probe_results[name] = {
            "query": query,
            "hits": sum(row[2] for row in rows),
            "trials_with_hits": len({row[0] for row in rows}),
            "primary_hits": sum(row[2] for row in rows if row[1] == "primary_report"),
            "supporting_hits": sum(
                row[2] for row in rows if row[1] == "supporting_source"
            ),
            "hits_per_trial": distribution(list(hits_by_trial.values())),
            "primary_hits_per_trial": distribution(
                list(primary_hits_by_trial.values())
            ),
        }

    role_counts = Counter(document["role"] for document in documents)
    report = {
        "method": {
            "liteparse_version": importlib.metadata.version("liteparse"),
            "ocr_enabled": False,
            "include_complexity": True,
            "output_format": "markdown",
            "fts5_tokenizer": "porter unicode61",
            "private_text_exported": False,
        },
        "corpus": {
            "documents": len(documents),
            "primary_reports": role_counts["primary_report"],
            "supporting_sources": role_counts["supporting_source"],
            "pages": sum(document["pages"] for document in documents),
            "bytes": sum(document["bytes"] for document in documents),
        },
        "runtime_seconds": round(time.perf_counter() - start_all, 3),
        "page_text_characters": distribution(page_lengths),
        "page_text_characters_by_role": {
            role: distribution(lengths)
            for role, lengths in page_lengths_by_role.items()
        },
        "needs_ocr": {
            "pages_by_role": {
                role: len(lengths)
                for role, lengths in needs_ocr_lengths_by_role.items()
            },
            "text_characters_by_role": {
                role: distribution(lengths)
                for role, lengths in needs_ocr_lengths_by_role.items()
            },
            "reason_sets": dict(needs_ocr_reason_sets.most_common()),
        },
        "targeted_primary_ocr": targeted_ocr,
        "canonical_unit_characters": distribution(unit_lengths),
        "canonical_units": len(unit_lengths),
        "complexity_reasons": dict(complexity_reasons.most_common()),
        "layout_reasons": dict(layout_reasons.most_common()),
        "probes": probe_results,
        "documents": documents,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(report["corpus"], indent=2))
    print(f"Runtime: {report['runtime_seconds']} seconds")
    print(f"Output: {args.output.resolve()}")


if __name__ == "__main__":
    main()
