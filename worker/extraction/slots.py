
import re
from dataclasses import dataclass
from decimal import Decimal

from domain.schemas import NumericSlots
from domain_packs.scientific_research import lexicon as lx


@dataclass(frozen=True)
class SlotContext:
    """Information inherited from a surrounding table or caption."""
    metric: str | None = None
    entity: str | None = None
    unit: str | None = None
    period: str | None = None
    denominator: str | None = None
    anchor_id: str | None = None


def _alt(words):
    """Build a regex alternative, checking longer phrases first."""
    return "|".join(
        sorted((re.escape(word) for word in words), key=len, reverse=True)
    )


# Numeric values: 120, -3.5, 2,100, 2,100.5
_NUM = (
    r"(?<![\w.])"
    r"(?P<sign>[-\u2212+])?"
    r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
)

# Optional suffix: percentage points, percent, or large-number scale
_SUF = (
    r"(?:\s?(?:"
    r"(?P<pp>(?i:percentage\s+points?|pp)\b)"
    r"|(?P<pct>%|(?i:percent)\b)"
    r"|(?P<scale>[KMB]\b|(?i:thousand|million|billion|bn)\b)"
    r"))?"
)

# Optional measurement unit
_UNIT = r"(?:\s?(?P<unit>" + _alt(lx.UNIT_TOKENS) + r")\b)?"

MENTION = re.compile(_NUM + _SUF + _UNIT)

_REF = re.compile(
    r"(?:Table|Tab\.|Figure|Fig\.|Section|Sec\.|Eq\.|Equation|Appendix)\s*$",
    re.I
)

_CITE = re.compile(r"\[\d+(?:\s*[,\u2013-]\s*\d+)*\]")

_FOLD = re.compile(r"\s?-?fold\b", re.I)
_KFOLD = re.compile(
    r"\b(\d+)-fold(?:\s+(?:cross[- ]validation|CV))?",
    re.I
)

_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")

_APPROX = re.compile(
    r"(?:about|approximately|approx\.?|roughly|around|nearly|~)\s*$",
    re.I
)

_ENTITY = re.compile(
    r"(?P<e>[A-Z][\w-]*(?:\s[A-Z0-9][\w-]*){0,3})\s+"
    r"(?:achieves|reaches|obtains|attains|yields|scores|reports|gets|improves)",
    re.I
)

_DENOM = re.compile(r"\bper\s+(\d[\d,]*|[a-z]+)", re.I)

_BASIS = re.compile(
    r"(?:vs\.?|versus|compared\s+(?:to|with)|than|over)\s+"
    r"((?:[A-Z0-9][\w-]*\s?){1,3})",
    re.I
)

_METRIC = re.compile(
    r"\b(" + _alt([
        word
        for aliases in lx.METRIC_ALIASES.values()
        for word in aliases
    ]) + r")\b",
    re.I
)

_SET = re.compile(
    r"\b(" + _alt([
        word
        for aliases in lx.PERIOD_ALIASES.values()
        for word in aliases
    ]) + r")\b",
    re.I
)

_ALIAS_ENT = re.compile(
    r"\b(" + _alt([
        word
        for aliases in lx.ENTITY_ALIASES.values()
        for word in aliases
    ]) + r")\b",
    re.I
)


def _canon(mapping, surface):
    """Convert a recognized surface form to its canonical name."""
    value = surface.casefold()

    for canonical, aliases in mapping.items():
        if value in [alias.casefold() for alias in aliases]:
            return canonical

    return None


def canonical_metric(text: str) -> str:
    cleaned = re.sub(r"\([^)]*\)", "", text).strip().casefold()
    return _canon(lx.METRIC_ALIASES, cleaned) or cleaned


def canonical_entity(text: str) -> str:
    return _canon(lx.ENTITY_ALIASES, text.strip()) or text.strip()


def _nearest_metric(text, position):
    best = None

    for match in _METRIC.finditer(text):
        distance = abs(match.start() - position)

        if best is None or distance < best[0]:
            best = (
                distance,
                _canon(lx.METRIC_ALIASES, match.group(0))
            )

    return best[1] if best else None


def _entity(text):
    match = _ALIAS_ENT.search(text)

    if match:
        return _canon(lx.ENTITY_ALIASES, match.group(0))

    match = _ENTITY.search(text)
    return match.group("e") if match else None


def find_period(text):
    match = _KFOLD.search(text)

    if match:
        return f"{match.group(1)}-fold cv"

    match = _SET.search(text)

    if match:
        return _canon(lx.PERIOD_ALIASES, match.group(0))

    match = _YEAR.search(text)
    return match.group(0) if match else None


def _valid_mentions(text):
    """Yield numeric mentions while ignoring citations, references and fold counts."""
    citations = [match.span() for match in _CITE.finditer(text)]

    for match in MENTION.finditer(text):

        # Ignore numbers inside citations such as [12] or [2, 3]
        if any(start <= match.start() < end for start, end in citations):
            continue

        # Ignore references such as Table 3 and Figure 2
        if _REF.search(text[:match.start()]):
            continue

        # Ignore the number in 5-fold CV
        if _FOLD.match(text, match.end()):
            continue

        number = match["num"]

        # Ignore standalone years such as 2024
        if (
            len(number) == 4
            and "." not in number
            and 1900 <= int(number) <= 2100
            and not any(match[group] for group in ("pp", "pct", "scale", "unit"))
        ):
            continue

        yield match


def _slot(text, match, context):
    raw_number = match["num"].replace(",", "")
    value = Decimal(raw_number)

    if match["sign"] in ("-", "\u2212"):
        value = -value

    if match["pp"]:
        unit = "percentage_point"
    elif match["pct"]:
        unit = "percent"
    elif match["unit"]:
        unit = lx.UNIT_TOKENS[match["unit"]]
    else:
        unit = context.unit

    scale = None

    if match["scale"]:
        scale = (
            lx.SCALES.get(match["scale"])
            or lx.SCALES.get(match["scale"].lower())
        )

    metric = _nearest_metric(text, match.start()) or context.metric

    # A bounded metric between 0 and 1 can be represented as a ratio
    if (
        unit is None
        and metric in lx.BOUNDED_RATIO_METRICS
        and Decimal(0) <= value <= 1
    ):
        unit = "ratio"

    denominator_match = _DENOM.search(text)
    basis_match = _BASIS.search(text)

    denominator_text = None

    if denominator_match:
        denominator_text = denominator_match.group(1).replace(",", "").lower()

    return NumericSlots(
        raw_text=match.group(0),
        metric=metric,
        entity=_entity(text) or context.entity,
        value=value,
        unit=unit,
        scale=scale,
        period=find_period(text) or context.period,
        comparison_basis=(
            basis_match.group(1).strip() if basis_match else None
        ),
        denominator=(
            f"per {denominator_text}"
            if denominator_text
            else context.denominator
        ),
        decimals=max(0, -Decimal(raw_number).as_tuple().exponent),
        approximate=bool(
            _APPROX.search(text[max(0, match.start() - 15):match.start()])
        ),
        source_anchor_id=context.anchor_id,
    )


def parse_all_numeric_slots(
    text: str,
    context: SlotContext | None = None
) -> list[NumericSlots]:
    """Extract every valid numeric mention from a sentence or chunk."""
    ctx = context or SlotContext()

    return [
        _slot(text, match, ctx)
        for match in _valid_mentions(text)
    ]


def parse_numeric_slots(
    text: str,
    context: SlotContext | None = None
) -> NumericSlots:
    """Return the first numeric slot, or an empty slot if none exists."""
    slots = parse_all_numeric_slots(text, context)

    return slots[0] if slots else NumericSlots(raw_text="")
