"""Render JSON Sources as readable Markdown page projections.

The captured JSON bytes stay the Source; this is only how they read. Objects
become headings, scalars `- key: value` lines and object lists numbered
entries, with every value copied literally. A ClinicalTrials.gov API v2 study
record also gets readable field labels, protocol before results, and
arm-by-row tables for the results modules so per-group counts read like a
paper table. Registry navigation (`domains._registry_navigation`) reads those
headings and `- Field: value` lines, so keep the two in step.
"""

from __future__ import annotations

import json
import re
from typing import Any

# Module headings (`## ...`). Navigation finds modules by these exact titles.
MODULE_TITLES = {
    "identificationModule": "Identification",
    "statusModule": "Status and dates",
    "sponsorCollaboratorsModule": "Sponsor and collaborators",
    "oversightModule": "Oversight",
    "descriptionModule": "Description",
    "conditionsModule": "Conditions",
    "designModule": "Design",
    "armsInterventionsModule": "Arms and interventions",
    "outcomesModule": "Registered outcomes",
    "eligibilityModule": "Eligibility",
    "contactsLocationsModule": "Contacts and locations",
    "referencesModule": "References",
    "ipdSharingStatementModule": "Individual participant data sharing",
    "participantFlowModule": "Results: participant flow",
    "baselineCharacteristicsModule": "Results: baseline characteristics",
    "outcomeMeasuresModule": "Results: outcome measures",
    "adverseEventsModule": "Results: adverse events",
    "moreInfoModule": "Results: more information",
    "largeDocumentModule": "Documents",
    "miscInfoModule": "Record information",
    "conditionBrowseModule": "Condition terms",
    "interventionBrowseModule": "Intervention terms",
}
SECTIONS = ("protocolSection", "resultsSection", "documentSection", "derivedSection")
# Headings (`### <name> N: <title>`) of registered and posted outcomes.
REGISTERED_OUTCOMES = {
    "primaryOutcomes": "Primary outcome",
    "secondaryOutcomes": "Secondary outcome",
    "otherOutcomes": "Other outcome",
}
POSTED_OUTCOME = "Outcome measure"


def is_ctgov_study(value: Any) -> bool:
    return isinstance(value, dict) and isinstance(value.get("protocolSection"), dict)


def label(key: str) -> str:
    """`studyFirstSubmitDate` -> `Study first submit date`; date structs drop `Struct`."""

    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", key.removesuffix("Struct")).split()
    return " ".join([words[0].capitalize(), *(w.lower() for w in words[1:])]) if words else key


def json_markdown(value: Any, name: str) -> str:
    if is_ctgov_study(value):
        return _Renderer(labels=True).study(value)
    renderer = _Renderer(labels=False)
    renderer.lines.append(f"# {name}")
    if isinstance(value, dict):
        renderer.block(value, 2)
    else:
        renderer.block({"value": value}, 2)
    return "\n".join(renderer.lines) + "\n"


def _text(value: Any) -> str:
    if value is None or isinstance(value, bool):
        return json.dumps(value)
    return str(value)


def _cell(value: Any) -> str:
    return _text(value).replace("\n", " ").replace("|", "\\|")


def _title(entry: Any) -> str:
    if not isinstance(entry, dict):
        return ""
    for key in ("measure", "title", "label", "name", "term"):
        if isinstance(entry.get(key), str):
            return entry[key].replace("\n", " ")
    return ""


def _scalars(value: dict | list) -> bool:
    items = value.values() if isinstance(value, dict) else value
    return all(not isinstance(x, (dict, list)) for x in items)


def _counts(items: list[dict[str, Any]]) -> dict[str, str]:
    """Group-keyed participant counts; units (for example eyes) follow the count."""

    cells = {}
    for item in items:
        value = _text(item.get("numSubjects", item.get("value", "")))
        if item.get("numUnits") is not None:
            value += f" ({item['numUnits']} units)"
        cells[str(item.get("groupId"))] = value
    return cells


def _measurement(item: dict[str, Any]) -> str:
    value = _text(item.get("value", ""))
    if item.get("spread") is not None:
        value += f" ({item['spread']})"
    if item.get("lowerLimit") is not None or item.get("upperLimit") is not None:
        value += f" ({item.get('lowerLimit', '')} to {item.get('upperLimit', '')})"
    if item.get("comment"):
        value += f" [{item['comment']}]"
    return value


class _Renderer:
    def __init__(self, *, labels: bool) -> None:
        self.lines: list[str] = []
        self.described: set[str] = set()
        # Generic JSON keeps its keys verbatim; registry keys read better as labels.
        self.name = label if labels else str

    def study(self, study: dict[str, Any]) -> str:
        nct = study["protocolSection"].get("identificationModule", {}).get("nctId", "")
        self.lines.append(f"# ClinicalTrials.gov record {nct}".rstrip())
        special = {
            "participantFlowModule": self.flow,
            "baselineCharacteristicsModule": self.baseline,
            "outcomeMeasuresModule": self.outcomes,
            "adverseEventsModule": self.adverse,
        }
        for section in SECTIONS:
            for key, module in (study.get(section) or {}).items():
                self.lines += ["", f"## {MODULE_TITLES.get(key, label(key))}"]
                special.get(key, lambda m: self.block(m, 3))(module)
        rest = {k: v for k, v in study.items() if k not in SECTIONS}
        if rest:
            self.lines += ["", "## Other fields"]
            self.block(rest, 3)
        return "\n".join(self.lines) + "\n"

    def block(self, value: Any, level: int) -> None:
        """Scalars as `- Label: value`; nested objects and object lists as headings."""

        if not isinstance(value, dict):
            self.lines.append(f"- {_text(value)}")
            return
        nested: list[tuple[str, Any]] = []
        for key, item in value.items():
            if isinstance(item, dict) and item and set(item) <= {"date", "type"}:
                kind = f" ({item['type']})" if "type" in item else ""
                self.lines.append(f"- {self.name(key)}: {item.get('date', '')}{kind}")
            elif isinstance(item, (dict, list)) and not _scalars(item):
                nested.append((key, item))
            elif isinstance(item, (dict, list)) and not item:
                self.lines.append(f"- {self.name(key)}: {'{}' if isinstance(item, dict) else '[]'}")
            elif isinstance(item, list):
                self.lines.append(f"- {self.name(key)}: {'; '.join(_text(x) for x in item)}")
            else:
                self.lines.append(f"- {self.name(key)}: {_text(item)}")
        for key, item in nested:
            if isinstance(item, dict):
                self.lines += ["", f"{'#' * level} {self.name(key)}"]
                self.block(item, level + 1)
                continue
            name = REGISTERED_OUTCOMES.get(key, self.name(key)) if self.name is label else key
            for index, entry in enumerate(item, 1):
                title = _title(entry)
                self.lines += [
                    "",
                    f"{'#' * level} {name} {index}" + (f": {title}" if title else ""),
                ]
                self.block(entry, level + 1)

    def groups(self, groups: list[dict[str, Any]]) -> tuple[list[str], dict[str, str]]:
        """List groups; each description is printed once per record, at its first use."""

        self.lines += ["", "Groups:"]
        for group in groups:
            text = _text(group.get("description") or "")
            description = f": {text}" if text and text not in self.described else ""
            if description:
                self.described.add(text)
            self.lines.append(f"- {group.get('id', '')} {group.get('title', '')}{description}")
        ids = [str(group.get("id", "")) for group in groups]
        return ids, {str(g.get("id")): str(g.get("title", g.get("id"))) for g in groups}

    def table(self, ids: list[str], titles: dict[str, str], rows: list[tuple[str, dict]]) -> None:
        self.lines += ["", "| | " + " | ".join(_cell(titles.get(i, i)) for i in ids) + " |"]
        self.lines.append("|---|" + "---|" * len(ids))
        for name, cells in rows:
            self.lines.append(
                f"| {_cell(name)} | " + " | ".join(_cell(cells.get(i, "")) for i in ids) + " |"
            )

    def flow(self, module: dict[str, Any]) -> None:
        self.block({k: v for k, v in module.items() if k not in {"groups", "periods"}}, 3)
        ids, titles = self.groups(module.get("groups") or [])
        for period in module.get("periods") or []:
            self.lines += ["", f"### Period: {period.get('title', '')}"]
            milestones = period.get("milestones") or []
            self.table(
                ids,
                titles,
                [(m.get("type", ""), _counts(m.get("achievements", []))) for m in milestones],
            )
            for milestone in milestones:
                for achievement in milestone.get("achievements", []):
                    if achievement.get("comment"):
                        self.lines.append(
                            f"- {milestone.get('type', '')}, {achievement.get('groupId')}: "
                            f"{achievement['comment']}"
                        )
                if milestone.get("comment"):
                    self.lines.append(f"- {milestone.get('type', '')}: {milestone['comment']}")
            withdrawals = period.get("dropWithdraws") or []
            if withdrawals:
                self.lines += ["", "Reasons for not completing:"]
                self.table(
                    ids,
                    titles,
                    [
                        (
                            w.get("type", "") + (f" ({w['comment']})" if w.get("comment") else ""),
                            _counts(w.get("reasons", [])),
                        )
                        for w in withdrawals
                    ],
                )

    def measures(self, measures: list[dict[str, Any]], heading: str, groups: list[dict]) -> None:
        for index, measure in enumerate(measures, 1):
            title = _title(measure)
            self.lines += ["", f"### {heading} {index}" + (f": {title}" if title else "")]
            skip = {"groups", "denoms", "classes", "analyses", "title"}
            self.block({k: v for k, v in measure.items() if k not in skip}, 4)
            if measure.get("groups"):
                ids, titles = self.groups(measure["groups"])
            else:
                ids = [str(g.get("id", "")) for g in groups]
                titles = {str(g.get("id")): str(g.get("title", g.get("id"))) for g in groups}
            rows = [
                (f"Analysed ({denom.get('units', '')})", _counts(denom.get("counts", [])))
                for denom in measure.get("denoms") or []
            ]
            for klass in measure.get("classes") or []:
                rows += [
                    (
                        f"{klass.get('title', '')}: analysed ({denom.get('units', '')})",
                        _counts(denom.get("counts", [])),
                    )
                    for denom in klass.get("denoms") or []
                ]
                for category in klass.get("categories") or []:
                    name = " / ".join(
                        x for x in (klass.get("title"), category.get("title")) if isinstance(x, str)
                    )
                    cells = {
                        str(m.get("groupId")): _measurement(m)
                        for m in category.get("measurements", [])
                    }
                    rows.append((name or "Value", cells))
            if rows:
                self.table(ids, titles, rows)
            for number, analysis in enumerate(measure.get("analyses") or [], 1):
                self.lines += ["", f"#### Statistical analysis {number}"]
                self.block(analysis, 5)

    def baseline(self, module: dict[str, Any]) -> None:
        self.block(
            {k: v for k, v in module.items() if k not in {"groups", "denoms", "measures"}}, 3
        )
        groups = module.get("groups") or []
        ids, titles = self.groups(groups)
        rows = [
            (f"Analysed ({denom.get('units', '')})", _counts(denom.get("counts", [])))
            for denom in module.get("denoms") or []
        ]
        if rows:
            self.table(ids, titles, rows)
        self.measures(module.get("measures") or [], "Baseline measure", groups)

    def outcomes(self, module: dict[str, Any]) -> None:
        self.block({k: v for k, v in module.items() if k != "outcomeMeasures"}, 3)
        self.measures(module.get("outcomeMeasures") or [], POSTED_OUTCOME, [])

    def adverse(self, module: dict[str, Any]) -> None:
        events = {"eventGroups", "seriousEvents", "otherEvents"}
        self.block({k: v for k, v in module.items() if k not in events}, 3)
        groups = module.get("eventGroups") or []
        ids, titles = self.groups(groups)
        fields = [
            k for k in (groups[0] if groups else {}) if k not in {"id", "title", "description"}
        ]
        if fields:
            self.table(
                ids,
                titles,
                [
                    (label(f), {str(g.get("id")): _text(g.get(f, "")) for g in groups})
                    for f in fields
                ],
            )
        for key, heading in (
            ("seriousEvents", "Serious adverse events"),
            ("otherEvents", "Other adverse events"),
        ):
            if not module.get(key):
                continue
            self.lines += ["", f"### {heading} (affected / at risk)"]
            rows = []
            for event in module[key]:
                name = f"{event.get('term', '')} ({event.get('organSystem', '')})" + "".join(
                    f"; {label(k)} {_text(v)}"
                    for k, v in event.items()
                    if k not in {"term", "organSystem", "stats"}
                )
                cells = {
                    str(s.get("groupId")): f"{s.get('numAffected', '')}/{s.get('numAtRisk', '')}"
                    + (f", {s['numEvents']} events" if s.get("numEvents") is not None else "")
                    for s in event.get("stats", [])
                }
                rows.append((name, cells))
            self.table(ids, titles, rows)
