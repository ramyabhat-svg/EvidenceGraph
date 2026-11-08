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

    # Roadmap assumption: first column identifies the entity.
    label = chunk.cells[headers[0]]
    entity = canonical_entity(label) if label else None

    # The caption may provide the period for the entire table.
    caption_period = find_period(chunk.caption or "")

    output = []

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
            metric=canonical_metric(header),
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