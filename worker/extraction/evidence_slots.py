import re

from domain.schemas import EvidenceChunk, NumericSlots
from domain_packs.scientific_research import lexicon as lx
from .slots import (
    SlotContext,
    canonical_entity,
    canonical_metric,
    find_period,
    parse_all_numeric_slots,
)


_HDR_UNIT = re.compile(r"\(([^)]*)\)\s*$")
_ENTITY_HEADER = re.compile(
    r"^(?:configuration|config|model|method|system)\s+[a-z0-9-]+$|^(?:ours|baseline|control)$",
    re.I,
)


def _metric_name(text: str) -> str:
    """Canonicalize a known metric label, retaining unknown labels as normalized text."""
    return canonical_metric(text)


def _is_metric_label(text: str) -> bool:
    """Return whether a table row label contains a recognized metric alias."""
    normalized = text.casefold()
    return any(
        alias.casefold() in normalized
        for aliases in lx.METRIC_ALIASES.values()
        for alias in aliases
    )


def _is_measure_matrix(headers: list[str], label: str) -> bool:
    """Recognize tables whose first column is a measure and other columns are entities."""
    first_header = headers[0].strip().casefold()
    return (
        first_header in {"measure", "metric", "outcome", "measure / metric"}
        or (_is_metric_label(label) and all(_ENTITY_HEADER.match(item.strip()) for item in headers[1:]))
    )


def slots_from_chunk(chunk: EvidenceChunk) -> list[NumericSlots]:
    """
    Extract numeric evidence slots from one evidence chunk.

    Paragraph chunks:
        Parse all numeric mentions from the paragraph text.

    Table/CSV row chunks:
        Treat the first column as the entity.
        Treat remaining column headers as metric names.
        Extract the first numeric value from each cell.
    """

    # Paragraph evidence: no structured cells are available.
    if chunk.cells is None:
        return parse_all_numeric_slots(
            chunk.text,
            SlotContext(anchor_id=chunk.anchor.anchor_id),
        )

    headers = list(chunk.cells)

    # A table row with no columns cannot produce evidence slots.
    if not headers:
        return []

    label = chunk.cells[headers[0]]
    caption_period = find_period(chunk.caption or "")
    output = []

    if _is_measure_matrix(headers, label):
        metric = _metric_name(label)
        for col, entity_header in enumerate(headers[1:], start=1):
            cell = chunk.cells[entity_header]
            if not cell:
                continue
            unit_match = _HDR_UNIT.search(label)
            header_unit = unit_match.group(1).strip() if unit_match else ""
            unit = (
                {"%": "percent", "percent": "percent"}.get(header_unit.casefold())
                or lx.UNIT_TOKENS.get(header_unit)
            )
            context = SlotContext(
                metric=metric,
                entity=canonical_entity(entity_header),
                unit=unit,
                period=find_period(label) or caption_period,
                anchor_id=f"{chunk.anchor.anchor_id}:c{col}",
            )
            slots = parse_all_numeric_slots(cell, context)
            if slots:
                output.append(slots[0])
        return output

    # Entity-row tables use the first column for an entity and the rest for metrics.
    entity = canonical_entity(label) if label else None

    # Remaining columns contain metrics and their values.
    for col, header in enumerate(headers[1:], start=1):
        cell = chunk.cells[header]

        if not cell:
            continue

        # Read a unit written at the end of the column header.
        unit_match = _HDR_UNIT.search(header)
        header_unit = unit_match.group(1).strip() if unit_match else ""

        unit = (
            {"%": "percent", "percent": "percent"}.get(
                header_unit.casefold()
            )
            or lx.UNIT_TOKENS.get(header_unit)
        )

        context = SlotContext(
            metric=_metric_name(header),
            entity=entity,
            unit=unit,
            period=find_period(header) or caption_period,
            anchor_id=f"{chunk.anchor.anchor_id}:c{col}",
        )

        # For values such as "91.2 ± 0.3", retain the main value.
        cell_slots = parse_all_numeric_slots(cell, context)

        if cell_slots:
            output.append(cell_slots[0])

    return output
