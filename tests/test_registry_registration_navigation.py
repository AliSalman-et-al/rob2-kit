from pathlib import Path

from rob2_kit.application._state import _db, _ensure, internal_path
from rob2_kit.application.domains import _registry_navigation

_SOURCE = "source_" + "a" * 64
_RECORD = "\n".join(
    [
        'protocolSection.outcomesModule.primaryOutcomes[0].measure: "All-cause death"',
        'protocolSection.outcomesModule.primaryOutcomes[0].timeFrame: "36 months"',
        'protocolSection.outcomesModule.secondaryOutcomes[0].measure: "Hospitalization"',
        'protocolSection.statusModule.startDateStruct.date: "2015-06"',
        'protocolSection.statusModule.studyFirstSubmitDate: "2015-04-30"',
    ]
)


def test_registered_outcomes_and_dates_are_navigable(tmp_path: Path) -> None:
    internal_path(tmp_path).mkdir()
    _ensure(tmp_path)
    with _db(tmp_path, "derivative.sqlite3") as connection:
        connection.execute("INSERT INTO pages VALUES (?,?,?)", (_SOURCE, 1, _RECORD))
    navigation = _registry_navigation(tmp_path, "trial", [{"id": _SOURCE, "role": "registry"}])[
        _SOURCE
    ]

    outcomes = {item["title"]: item for item in navigation["outcomes"]}
    assert outcomes["All-cause death"]["type"] == "REGISTERED PRIMARY"
    assert outcomes["All-cause death"]["timeFrame"] == "36 months"
    assert outcomes["Hospitalization"]["type"] == "REGISTERED SECONDARY"
    registration = navigation["registration"]
    assert (registration["first_submitted"], registration["start"]) == ("2015-04-30", "2015-06")
    assert registration["recovery"]["windows"][0]["start_line"] == 4
