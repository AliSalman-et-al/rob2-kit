"""Strict field and table provenance layered over the base validators."""

from __future__ import annotations

from collections.abc import Mapping

from . import provenance_legacy as _legacy

FieldEvidenceBinding = _legacy.FieldEvidenceBinding
TableCellBinding = _legacy.TableCellBinding
TableAxisMap = _legacy.TableAxisMap
ProvenanceDeclaration = _legacy.ProvenanceDeclaration
ProvenanceDefect = _legacy.ProvenanceDefect
EvidenceTextResolver = _legacy.EvidenceTextResolver
normalize = _legacy.normalize
value_is_present = _legacy.value_is_present
validate_field_bindings = _legacy.validate_field_bindings
validate_table_semantics = _legacy.validate_table_semantics


def _category_for_cell(card: Mapping[str, object], path: str) -> str:
    parts = path.strip("/").split("/")
    if len(parts) < 4 or parts[-1] != "value" or parts[-3] not in {
        "categories",
        "quantities",
    }:
        return ""
    sibling = "/" + "/".join((*parts[:-1], "group_or_category"))
    try:
        return normalize(_legacy._at_pointer(card, sibling))
    except (KeyError, ValueError, IndexError):
        return ""


def validate_complete_reported_provenance(
    card: Mapping[str, object],
    declaration: ProvenanceDeclaration,
    resolver: EvidenceTextResolver,
) -> tuple[ProvenanceDefect, ...]:
    """Require exact endpoint identity and prevent table-axis broadening."""

    defects = list(
        _legacy.validate_complete_reported_provenance(card, declaration, resolver)
    )
    if declaration.relationship_to_requested not in {"exact", "operationalization"}:
        defects.append(
            ProvenanceDefect(
                pointer="/provenance/relationship_to_requested",
                code="endpoint_mismatch_requires_clarification",
                detail=(
                    "a broader, narrower, component, or merely related endpoint "
                    "cannot replace the requested Result"
                ),
            )
        )
    if declaration.table is not None:
        cumulative_words = ("or higher", "or worse", "+", "at least")
        for cell in declaration.table_cells:
            category = _category_for_cell(card, cell.path)
            if not any(word in category for word in cumulative_words):
                continue
            source_column = normalize(cell.column_label)
            explicitly_cumulative = (
                cell.column_label in declaration.table.cumulative_columns
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
    unique = {(item.pointer, item.code, item.detail): item for item in defects}
    return tuple(unique[key] for key in sorted(unique))


__all__ = [
    "EvidenceTextResolver",
    "FieldEvidenceBinding",
    "ProvenanceDeclaration",
    "ProvenanceDefect",
    "TableAxisMap",
    "TableCellBinding",
    "normalize",
    "validate_complete_reported_provenance",
    "validate_field_bindings",
    "validate_table_semantics",
    "value_is_present",
]
