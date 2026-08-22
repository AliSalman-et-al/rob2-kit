"""Agent-oriented Evidence selection over the canonical Evidence store."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from rob2_kit.sources import _extract_pages, verified_source_bytes

from ._state import write_json
from .contracts import EvidenceReference
from .evidence import (
    EvidenceCatalogRequest,
    EvidenceRetrievalRequest,
    ManualSelectionRequest,
    NormalSelectionRequest,
    PageReadRequest,
    SearchContinuation,
    SearchRequest,
    VisualSelectionRequest,
    list_sources,
    resolve_evidence,
    retrieve_evidence,
    source_layout_projection,
    source_records,
)
from .transport import TransportRepairReceipt, validation_repairs


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class QuoteSelectionRequest(_Closed):
    source_alias: str = Field(min_length=1)
    page: int = Field(ge=1)
    quote: str = Field(min_length=1)
    occurrence: int | None = Field(default=None, ge=1)


class TableSelectionRequest(QuoteSelectionRequest):
    title: str = Field(min_length=1)
    population: str = Field(min_length=1)
    row_axis: str = Field(min_length=1)
    column_axis: str = Field(min_length=1)
    row_label: str = Field(min_length=1)
    column_label: str = Field(min_length=1)
    value: str | int | float
    unit: str = Field(min_length=1)
    denominator_basis: str = Field(min_length=1)
    aggregation: Literal["as_reported", "cumulative", "derived"] = "as_reported"
    footnotes: tuple[str, ...] = ()


_ModelT = TypeVar("_ModelT", bound=BaseModel)


def _models(model: type[_ModelT], values: object) -> tuple[_ModelT, ...]:
    if values is None:
        return ()
    if not isinstance(values, Sequence) or isinstance(values, str | bytes | bytearray):
        raise TypeError("operation collection must be an array")
    return tuple(model.model_validate(value) for value in values)


def _page(workspace: str | Path, trial_id: str, source_alias: str, page: int) -> str:
    aliases = list_sources(workspace, trial_id)
    sources = source_records(workspace, trial_id)
    by_alias = {alias.alias: source for alias, source in zip(aliases, sources, strict=True)}
    source = by_alias.get(source_alias)
    if source is None:
        raise KeyError(source_alias)
    pages = _extract_pages(
        verified_source_bytes(Path(workspace).resolve(strict=True), source), source.media_type
    )
    if page > len(pages):
        raise IndexError(page)
    return pages[page - 1]


def _occurrences(text: str, quote: str) -> tuple[tuple[int, int], ...]:
    exact: list[tuple[int, int]] = []
    start = 0
    while (found := text.find(quote, start)) >= 0:
        exact.append((found, found + len(quote)))
        start = found + max(1, len(quote))
    if exact:
        return tuple(exact)
    projected, starts, ends = source_layout_projection(text)
    projected_quote = source_layout_projection(quote)[0]
    if not projected_quote:
        return ()
    normalized: list[tuple[int, int]] = []
    start = 0
    while (found := projected.find(projected_quote, start)) >= 0:
        end = found + len(projected_quote)
        normalized.append((starts[found], ends[end - 1]))
        start = end
    return tuple(normalized)


def _manual(
    workspace: str | Path,
    trial_id: str,
    selection: QuoteSelectionRequest,
) -> ManualSelectionRequest | dict[str, object]:
    try:
        text = _page(workspace, trial_id, selection.source_alias, selection.page)
    except KeyError:
        return {
            "code": "source_out_of_scope",
            "detail": selection.source_alias,
            "next_action": "use_list_sources",
        }
    except IndexError:
        return {
            "code": "page_out_of_range",
            "detail": str(selection.page),
            "next_action": "read_exact_page",
        }
    matches = _occurrences(text, selection.quote)
    if not matches:
        return {
            "code": "no_hits",
            "detail": "the selected quote is absent from the frozen page text",
            "next_action": "read_exact_page",
        }
    if selection.occurrence is None and len(matches) != 1:
        return {
            "code": "ambiguous",
            "detail": f"the quote occurs {len(matches)} times on the page",
            "next_action": "set_occurrence",
        }
    occurrence = selection.occurrence or 1
    if occurrence > len(matches):
        return {
            "code": "ambiguous",
            "detail": f"occurrence {occurrence} exceeds {len(matches)} matches",
            "next_action": "set_occurrence",
        }
    start, end = matches[occurrence - 1]
    return ManualSelectionRequest(
        kind="manual_selection",
        source_alias=selection.source_alias,
        page=selection.page,
        start=start,
        end=end,
        quote=text[start:end],
    )


def _dump_response(result: BaseModel | None) -> dict[str, object]:
    if result is None:
        return {
            "snapshot": "",
            "hits": [],
            "continuations": [],
            "page_reads": [],
            "evidence": [],
            "conditions": [],
        }
    return result.model_dump(mode="json", exclude_none=True)


def _sequence(value: object) -> list[object]:
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return list(value)
    return []


def retrieve_agent_evidence(
    workspace: str | Path, raw: Mapping[str, Any]
) -> dict[str, object] | TransportRepairReceipt:
    """Run canonical retrieval plus quote/table conveniences.

    Selected Evidence records are returned inline, so a caller need not spend a
    second round trip resolving an identity it just minted.
    """

    try:
        trial_id = str(raw["trial_id"])
        searches = _models(SearchRequest, raw.get("searches"))
        continuations = _models(SearchContinuation, raw.get("continuations"))
        page_reads = _models(PageReadRequest, raw.get("page_reads"))
        normal = _models(NormalSelectionRequest, raw.get("normal_selections"))
        manual = _models(ManualSelectionRequest, raw.get("manual_selections"))
        visual = _models(VisualSelectionRequest, raw.get("visual_selections"))
        quote_selections = tuple(
            QuoteSelectionRequest.model_validate(value)
            for value in _sequence(raw.get("quote_selections"))
        )
        table_selections = tuple(
            TableSelectionRequest.model_validate(value)
            for value in _sequence(raw.get("table_selections"))
        )
        catalog_raw = raw.get("catalog")
        catalog = (
            None if catalog_raw is None else EvidenceCatalogRequest.model_validate(catalog_raw)
        )
    except (KeyError, TypeError, ValidationError) as error:
        if isinstance(error, ValidationError):
            return validation_repairs(error)
        return {
            "outcome": "repair",
            "repairs": [
                {
                    "pointer": "/trial_id" if isinstance(error, KeyError) else "",
                    "code": "missing" if isinstance(error, KeyError) else "wrong_type",
                    "detail": str(error),
                }
            ],
        }

    base_result = None
    if any((searches, continuations, page_reads, normal, manual, visual, catalog)):
        try:
            base_request = EvidenceRetrievalRequest(
                trial_id=trial_id,
                searches=searches,
                continuations=continuations,
                page_reads=page_reads,
                normal_selections=normal,
                manual_selections=manual,
                visual_selections=visual,
                catalog=catalog,
            )
        except ValidationError as error:
            return validation_repairs(error)
        base_result = retrieve_evidence(workspace, base_request)

    selections: tuple[QuoteSelectionRequest, ...] = (*quote_selections, *table_selections)
    convenience_conditions: list[dict[str, object]] = []
    selected_refs: list[EvidenceReference] = []
    table_records: list[dict[str, object]] = []
    snapshot = ""
    if selections:
        manuals: list[ManualSelectionRequest] = []
        accepted: list[QuoteSelectionRequest] = []
        for selection in selections:
            resolved = _manual(workspace, trial_id, selection)
            if isinstance(resolved, dict):
                convenience_conditions.append(resolved)
            else:
                manuals.append(resolved)
                accepted.append(selection)
        if manuals:
            selected = retrieve_evidence(
                workspace,
                EvidenceRetrievalRequest(trial_id=trial_id, manual_selections=tuple(manuals)),
            )
            snapshot = selected.snapshot
            selected_refs.extend(selected.evidence)
            convenience_conditions.extend(
                item.model_dump(mode="json") for item in selected.conditions
            )
            for selection, reference in zip(accepted, selected.evidence, strict=True):
                if not isinstance(selection, TableSelectionRequest):
                    continue
                metadata = {
                    "kind": "table_cell_evidence",
                    "evidence": reference.model_dump(mode="json"),
                    "title": selection.title,
                    "population": selection.population,
                    "row_axis": selection.row_axis,
                    "column_axis": selection.column_axis,
                    "row_label": selection.row_label,
                    "column_label": selection.column_label,
                    "value": selection.value,
                    "unit": selection.unit,
                    "denominator_basis": selection.denominator_basis,
                    "aggregation": selection.aggregation,
                    "footnotes": list(selection.footnotes),
                }
                write_json(
                    workspace,
                    f"table-evidence-{reference.identity.removeprefix('sha256:')}.json",
                    metadata,
                )
                table_records.append(metadata)

    payload = _dump_response(base_result)
    if not payload.get("snapshot"):
        payload["snapshot"] = snapshot
    existing_evidence = _sequence(payload.get("evidence"))
    payload["evidence"] = [
        *existing_evidence,
        *[reference.model_dump(mode="json") for reference in selected_refs],
    ]
    existing_conditions = _sequence(payload.get("conditions"))
    payload["conditions"] = [*existing_conditions, *convenience_conditions]
    records: list[dict[str, object]] = []
    for raw_ref in _sequence(payload.get("evidence")):
        try:
            reference = EvidenceReference.model_validate(raw_ref)
            records.append(resolve_evidence(workspace, reference).model_dump(mode="json"))
        except (TypeError, ValueError):
            continue
    payload["records"] = records
    payload["table_bindings"] = table_records
    payload["outcome"] = "success" if not _sequence(payload.get("conditions")) else "condition"
    return payload