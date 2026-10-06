"""Bounded checks of the real frozen corpus and semantic limits; no app mutation."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

from rob2_kit.application.evidence import _numeric_contains

ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("numeric_absence_audit", ROOT / "audit.py")
assert SPEC is not None and SPEC.loader is not None
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


def load(name: str):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def test_frozen_real_case_replay_and_original_immutability() -> None:
    freeze = load("freeze.json")
    sample = load("sample.json")
    before = {p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in freeze["bundles"]}
    assert before == freeze["bundles"]
    assert [AUDIT.inspect(row) for row in sample] == load("results.json")["results"]
    assert {p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in before} == before
    assert len({r["case"] for r in sample if r["sample_role"] == "control"}) == 13


def test_present_value_does_not_bind_the_quantity_or_units() -> None:
    sample = load("sample.json")
    getgood = next(r for r in sample if r["case"] == "getgood-2020")
    quote = getgood["selected"][0]["evidence"]["quote"]
    assert "Primary analysis (15% missing)" in quote
    assert _numeric_contains(quote, "15", allow_percent_suffix=True)
    # That percentage is for PROs; the warrant's 15 is the sum of LET losses.
    assert "Lost to follow-up (n = 10)" in quote and "Withdrawn (n = 5)" in quote
    albert = next(r for r in sample if r["case"] == "albert-2013")
    table = albert["selected"][1]["evidence"]["quote"]
    assert _numeric_contains(table, "18", allow_percent_suffix=True)
    assert "quartile" in table  # Not direct evidence of 18 missing participants.


def test_derived_typed_missing_counts_are_not_required_source_literals() -> None:
    sample = load("sample.json")
    nefi = next(r for r in sample if r["case"] == "nefigard")
    rows = nefi["answer"]["missing_data"]["rows"]
    assert len(rows) == 4
    for row in rows:
        assert row["missing"] == row["randomized"] - row["observed"]
    checked = AUDIT.inspect(nefi)["typed_quantity_checks"]
    assert {c["value"] for c in checked if c["field"] == "missing"} == {33, 36, 21, 17}
    assert all(c["literal_absent"] for c in checked if c["field"] == "missing")
    assert all(not c["literal_absent"] for c in checked if c["field"] == "observed")


def test_correct_elsewhere_fact_and_every_control_flag_are_explained() -> None:
    sample = load("sample.json")
    dapa = next(r for r in sample if r["case"] == "dapa-hf")
    quote = dapa["selected"][0]["evidence"]["quote"]
    elsewhere = load("elsewhere-context.json")
    assert elsewhere["source_id"] == dapa["selected"][0]["evidence"]["source_id"]
    for number in ("386", "502"):
        assert not _numeric_contains(quote, number)
        assert _numeric_contains(elsewhere["numbered_text"], number)
    result = load("results.json")["results"]
    notes = load("adjudication.json")["rows"]
    assert [(r["case"], r["question"], r["absent"]) for r in result] == [
        (r["case"], r["question"], r["primary_flags"]) for r in notes
    ]
    assert all(r["explanation"] for r in notes)
    assert all(
        r["before_runtime_annotation"] is r["after_runtime_annotation"] is None for r in notes
    )
