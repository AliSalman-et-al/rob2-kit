"""Field-level scientific provenance and table-axis validation.

This module intentionally performs deterministic checks only. It verifies that
structured values, labels, roles, and table coordinates are present in the
exact persisted Evidence chosen by the caller. It does not infer clinical
meaning or replace researcher review.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .contracts import EvidenceReference

_NUMBER = re.compile(
    r"(?<![A-Za-z0-9])(?:[<>]=?\s*)?[-+]?\d+(?:\.\d+)?%?(?![A-Za-z0-9])"
)


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FieldEvidenceBinding(_Closed):
    path: str = Field(
        pattern=r"^/(?:[^~/]|~[01])+(?:/(?:[^~/]|~[01])+)*$"
    )
    evidence: tuple[EvidenceReference, ...] = Field(min_length=1)
    required_terms: tuple[str, ...] = ()
    required_values: tuple[str | int | float, ...] = ()
    source_row: str | None = Field(default=None, min_length=1)
    source_column: str | None = Field(default=None, min_length=1)
    source_group: str | None = Field(default=None, min_length=1)
    source_unit: str | None = Field(default=None, min_length=1)
    denominator_basis: str | None = Field(default=None, min_length=1)


class TableCellBinding(_Closed):
    path: str = Field(
        pattern=r"^/(?:[^~/]|~[01])+(?:/(?:[^~/]|~[01])+)*$"
    )
    evidence: EvidenceReference
    row_label: str = Field(min_length=1)
    column_label: str = Field(min_length=1)
    raw_text: str = Field(min_length=1)
    value: str | int | float
    unit: str = Field(min_length=1)
    denominator_basis: str = Field(min_length=1)
    aggregation: Literal["as_reported", "cumulative", "derived"] = "as_reported"


class TableAxisMap(_Closed):
    title: str = Field(min_length=1)
    population: str = Field(min_length=1)
    row_axis: str = Field(min_length=1)
    column_axis: str = Field(min_length=1)
    row_labels: tuple[str, ...] = Field(min_length=1)
    column_labels: tuple[str, ...] = Field(min_length=1)
    required_cells: tuple[tuple[str, str], ...] = ()
    cumulative_columns: tuple[str, ...] = ()
    footnotes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def cells_bind_declared_axes(self) -> TableAxisMap:
        rows, columns = set(self.row_labels), set(self.column_labels)
        if any(
            row not in rows or column not in columns
            for row, column in self.required_cells
        ):
            raise ValueError(
                "required table cells must use declared row and column labels"
            )
        if set(self.cumulative_columns) - columns:
            raise ValueError("cumulative columns must be declared table columns")
        return self


class ProvenanceDeclaration(_Closed):
    source_reported_outcome: str = Field(min_length=1)
    relationship_to_requested: Literal[
        "exact",
        "operationalization",
        "broader",
        "narrower",
        "component",
        "related",
    ]
    field_bindings: tuple[FieldEvidenceBinding, ...] = Field(min_length=1)
    table: TableAxisMap | None = None
    table_cells: tuple[TableCellBinding, ...] = ()

    @model_validator(mode="after")
    def table_parts_are_paired(self) -> ProvenanceDeclaration:
        if (self.table is None) != (not self.table_cells):
            raise ValueError(
                "table axis metadata and table-cell bindings must be supplied together"
            )
        return self


class ProvenanceDefect(_Closed):
    pointer: str
    code: str
    detail: str


EvidenceTextResolver = Callable[[EvidenceReference], str]


def normalize(value: object) -> str:
    text = str(value).casefold().replace("–", "-").replace("—", "-")
    return " ".join(text.split())


def _decimal(value: object) -> Decimal | None:
    if isinstance(value, bool):
        return None
    try:
        return Decimal(str(value).strip().rstrip("%"))
    except (InvalidOperation, ValueError):
        return None


def _number_tokens(text: str) -> tuple[Decimal, ...]:
    tokens: list[Decimal] = []
    for match in _NUMBER.finditer(text.replace("−", "-")):
        token = re.sub(r"^[<>]=?\s*", "", match.group()).rstrip("%")
        try:
            tokens.append(Decimal(token))
        except InvalidOperation:
            continue
    return tuple(tokens)


def value_is_present(text: str, value: object) -> bool:
    expected = _decimal(value)
    if expected is not None:
        return expected in _number_tokens(text)
    return normalize(value) in normalize(text)


def _at_pointer(value: Mapping[str, object], pointer: str) -> object:
    current: object = value
    for raw in pointer.lstrip("/").split("/"):
        key = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping):
            if key not in current:
                raise KeyError(pointer)
            current = current[key]
        elif isinstance(current, Sequence) and not isinstance(
            current, str | bytes | bytearray
        ):
            current = current[int(key)]
        else:
            raise KeyError(pointer)
    return current


def _texts(
    binding: FieldEvidenceBinding, resolver: EvidenceTextResolver
) -> tuple[str, ...]:
    return tuple(resolver(reference) for reference in binding.evidence)


def validate_field_bindings(
    card: Mapping[str, object],
    declaration: ProvenanceDeclaration,
    resolver: EvidenceTextResolver,
) -> tuple[ProvenanceDefect, ...]:
    defects: list[ProvenanceDefect] = []
    by_path = {binding.path: binding for binding in declaration.field_bindings}
    if len(by_path) != len(declaration.field_bindings):
        defects.append(
            ProvenanceDefect(
                pointer="/provenance/field_bindings",
                code="duplicate",
                detail="field binding paths must be unique",
            )
        )
    for binding in declaration.field_bindings:
        try:
            structured = _at_pointer(card, binding.path)
        except (KeyError, ValueError, IndexError):
            defects.append(
                ProvenanceDefect(
                    pointer=binding.path,
                    code="unknown_path",
                    detail="field binding does not name a structured Result field",
                )
            )
            continue
        texts = _texts(binding, resolver)
        combined = "\n".join(texts)
        required_values = binding.required_values or (structured,)
        for expected in required_values:
            if not any(value_is_present(text, expected) for text in texts):
                defects.append(
                    ProvenanceDefect(
                        pointer=binding.path,
                        code="value_not_in_evidence",
                        detail=(
                            f"structured value {expected!r} is absent from its "
                            "bound Evidence"
                        ),
                    )
                )
        terms = (
            *binding.required_terms,
            *tuple(
                item
                for item in (
                    binding.source_row,
                    binding.source_column,
                    binding.source_group,
                    binding.source_unit,
                    binding.denominator_basis,
                )
                if item
            ),
        )
        for term in terms:
            if normalize(term) not in normalize(combined):
                defects.append(
                    ProvenanceDefect(
                        pointer=binding.path,
                        code="label_not_in_evidence",
                        detail=(
                            f"source label {term!r} is absent from its bound "
                            "Evidence"
                        ),
                    )
                )
    return tuple(defects)


def _reported_atoms(card: Mapping[str, object]) -> tuple[tuple[str, object], ...]:
    reported = card.get("reported")
    if not isinstance(reported, Mapping):
        return ()
    atoms: list[tuple[str, object]] = []
    effect = reported.get("effect")
    if isinstance(effect, Mapping):
        for key in ("statistic", "group_or_category", "value", "denominator_basis"):
            if effect.get(key) is not None:
                atoms.append((f"/reported/effect/{key}", effect[key]))
    quantities = reported.get("quantities")
    if isinstance(quantities, Sequence) and not isinstance(
        quantities, str | bytes | bytearray
    ):
        for index, quantity in enumerate(quantities):
            if not isinstance(quantity, Mapping):
                continue
            for key in (
                "statistic",
                "unit",
                "group_or_category",
                "value",
                "denominator_basis",
            ):
                if quantity.get(key) is not None:
                    atoms.append((f"/reported/quantities/{index}/{key}", quantity[key]))
    precision = reported.get("precision")
    if isinstance(precision, Mapping):
        interval = precision.get("confidence_interval")
        if isinstance(interval, Mapping):
            for key in ("level", "lower", "upper"):
                if interval.get(key) is not None:
                    atoms.append(
                        (f"/reported/precision/confidence_interval/{key}", interval[key])
                    )
        p_value = precision.get("p_value")
        if isinstance(p_value, Mapping):
            for key in ("operator", "value"):
                if p_value.get(key) is not None:
                    atoms.append((f"/reported/precision/p_value/{key}", p_value[key]))
    categories = reported.get("categories")
    if isinstance(categories, Sequence) and not isinstance(
        categories, str | bytes | bytearray
    ):
        for index, category in enumerate(categories):
            if not isinstance(category, Mapping):
                continue
            for key in (
                "statistic",
                "unit",
                "group_or_category",
                "value",
                "denominator_basis",
            ):
                if category.get(key) is not None:
                    atoms.append((f"/reported/categories/{index}/{key}", category[key]))
    return tuple(atoms)


def validate_complete_reported_provenance(
    card: Mapping[str, object],
    declaration: ProvenanceDeclaration,
    resolver: EvidenceTextResolver,
) -> tuple[ProvenanceDefect, ...]:
    defects = list(validate_field_bindings(card, declaration, resolver))
    bound = {binding.path for binding in declaration.field_bindings}
    for pointer, _value in _reported_atoms(card):
        if pointer not in bound:
            defects.append(
                ProvenanceDefect(
                    pointer=pointer,
                    code="missing_field_evidence",
                    detail=(
                        "every structured reported atom requires an explicit "
                        "Evidence binding"
                    ),
                )
            )
    outcome_text = normalize(declaration.source_reported_outcome)
    all_text = normalize(
        "\n".join(
            resolver(reference)
            for binding in declaration.field_bindings
            for reference in binding.evidence
        )
    )
    if outcome_text not in all_text:
        defects.append(
            ProvenanceDefect(
                pointer="/provenance/source_reported_outcome",
                code="endpoint_not_in_evidence",
                detail=(
                    "the source-reported endpoint label or definition is absent "
                    "from bound Evidence"
                ),
            )
        )
    defects.extend(validate_table_semantics(card, declaration, resolver))
    unique = {(item.pointer, item.code, item.detail): item for item in defects}
    return tuple(unique[key] for key in sorted(unique))


def validate_table_semantics(
    card: Mapping[str, object],
    declaration: ProvenanceDeclaration,
    resolver: EvidenceTextResolver,
) -> tuple[ProvenanceDefect, ...]:
    if declaration.table is None:
        return ()
    table = declaration.table
    defects: list[ProvenanceDefect] = []
    seen: set[tuple[str, str]] = set()
    for cell in declaration.table_cells:
        coordinate = (cell.row_label, cell.column_label)
        if coordinate in seen:
            defects.append(
                ProvenanceDefect(
                    pointer=cell.path,
                    code="duplicate_table_cell",
                    detail=f"table cell {coordinate!r} is bound more than once",
                )
            )
        seen.add(coordinate)
        evidence_text = resolver(cell.evidence)
        for label in (table.title, cell.row_label, cell.column_label):
            if normalize(label) not in normalize(evidence_text):
                defects.append(
                    ProvenanceDefect(
                        pointer=cell.path,
                        code="table_axis_not_in_evidence",
                        detail=(
                            f"table label {label!r} is absent from the cell Evidence"
                        ),
                    )
                )
        if not value_is_present(evidence_text, cell.value):
            defects.append(
                ProvenanceDefect(
                    pointer=cell.path,
                    code="table_value_not_in_evidence",
                    detail=(
                        f"table value {cell.value!r} is absent from the cell Evidence"
                    ),
                )
            )
        try:
            structured = normalize(_at_pointer(card, cell.path))
        except (KeyError, ValueError, IndexError):
            defects.append(
                ProvenanceDefect(
                    pointer=cell.path,
                    code="unknown_path",
                    detail="table cell does not bind a structured Result field",
                )
            )
            continue
        source_column = normalize(cell.column_label)
        cumulative_words = ("or higher", "or worse", "+", "at least")
        if any(word in structured for word in cumulative_words):
            explicitly_cumulative = (
                cell.column_label in table.cumulative_columns
                or any(word in source_column for word in cumulative_words)
            )
            if not explicitly_cumulative:
                defects.append(
                    ProvenanceDefect(
                        pointer=cell.path,
                        code="unsupported_cumulative_category",
                        detail=(
                            "a source grade/category was broadened into a "
                            "cumulative threshold"
                        ),
                    )
                )
    missing = set(table.required_cells) - seen
    if missing:
        defects.append(
            ProvenanceDefect(
                pointer="/provenance/table_cells",
                code="incomplete_table_profile",
                detail=f"required source table cells are missing: {sorted(missing)!r}",
            )
        )
    return tuple(defects)
