import json
import sqlite3
from pathlib import Path

from rob2_kit.application import domains
from rob2_kit.application._state import _json_pages

STUDY = {
    "protocolSection": {
        "identificationModule": {"nctId": "NCT00000001"},
        "statusModule": {
            "studyFirstSubmitDate": "2014-09-18",
            "startDateStruct": {"date": "2014-11-06", "type": "ACTUAL"},
        },
        "outcomesModule": {
            "primaryOutcomes": [
                {"measure": "Progression-free survival", "timeFrame": "Up to 4 years"}
            ]
        },
    },
    "resultsSection": {
        "participantFlowModule": {
            "groups": [{"id": "FG000", "title": "Drug"}, {"id": "FG001", "title": "Placebo"}],
            "periods": [
                {
                    "title": "Overall Study",
                    "milestones": [
                        {
                            "type": "STARTED",
                            "achievements": [
                                {"groupId": "FG000", "numSubjects": "328"},
                                {"groupId": "FG001", "numSubjects": "165"},
                            ],
                        }
                    ],
                }
            ],
        },
        "outcomeMeasuresModule": {
            "outcomeMeasures": [
                {
                    "type": "PRIMARY",
                    "title": "Progression-free survival",
                    "timeFrame": "Up to 4 years",
                    "groups": [{"id": "OG000", "title": "Drug"}],
                    "classes": [
                        {"categories": [{"measurements": [{"groupId": "OG000", "value": "28.2"}]}]}
                    ],
                }
            ]
        },
    },
}


def _navigation(tmp_path: Path, text: str) -> dict:
    (tmp_path / ".rob2-kit").mkdir()
    with sqlite3.connect(tmp_path / ".rob2-kit" / "derivative.sqlite3") as connection:
        connection.execute("CREATE TABLE pages (page INTEGER, text TEXT, source_id TEXT)")
        connection.execute("INSERT INTO pages VALUES (1, ?, 'sh_registry')", (text,))
    return domains._registry_navigation(
        tmp_path, "trial", [{"id": "sh_registry", "role": "registry"}]
    )["sh_registry"]


def test_registry_record_reads_as_markdown_with_navigable_dates_and_outcomes(tmp_path):
    (text,) = _json_pages(Path("registry.json"), json.dumps(STUDY).encode())
    lines = text.splitlines()
    assert "| STARTED | 328 | 165 |" in lines
    assert "- Study first submit date: 2014-09-18" in lines

    navigation = _navigation(tmp_path, text)
    registration = navigation["registration"]
    assert (registration["first_submitted"], registration["start"]) == ("2014-09-18", "2014-11-06")
    registered, posted = navigation["outcomes"]
    assert (registered["type"], registered["title"], registered["timeFrame"]) == (
        "REGISTERED PRIMARY",
        "Progression-free survival",
        "Up to 4 years",
    )
    assert posted["type"] == "PRIMARY"
    window = posted["recovery"]["windows"][0]
    assert "28.2" in "\n".join(lines[window["start_line"] - 1 : window["end_line"]])
    assert "Results: participant flow" in navigation["paths"]


def test_other_json_keeps_keys_and_values_literally():
    data = {"n_randomized": 120, "arms": [{"name": "A", "missing": None}], "notes": "two\nlines"}
    (text,) = _json_pages(Path("extract.json"), json.dumps(data).encode())
    assert text.splitlines()[:2] == ["# extract.json", "- n_randomized: 120"]
    assert "## arms 1: A" in text and "- missing: null" in text and "two\nlines" in text
