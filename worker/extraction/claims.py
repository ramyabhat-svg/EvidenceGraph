"""Extract independently verifiable numeric assertions from paragraph evidence."""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Iterable

from domain.schemas import AnchorKind, Claim, ClaimType, EvidenceChunk
from worker.ingestion.anchors import stable_uuid
from worker.extraction.slots import SlotContext, parse_all_numeric_slots

EXTRACTOR_VERSION = "rules-2"

_COMPARATIVE = re.compile(
    r"\b(outperform\w*|improv\w*|higher|lower|better|worse|than|versus|vs\.?|"
    r"increase\w*|decrease\w*|difference)\b",
    re.I,
)
_ASSERTION = re.compile(
    r"\b(?:is|are|was|were|has|have|had|contains?|includes?|reports?|returned?|"
    r"achiev\w*|obtain\w*|reach\w*|yield\w*|score\w*|increased?|decreased?|"
    r"improv\w*|reduc\w*|exceeds?|equals?|remain\w*|uses?|evaluated|shows?|"
    r"outperform\w*|performs?)\b",
    re.I,
)
_CLAIM_MARKER = re.compile(r"^\s*Claim\s+[A-Z]?\d+\.\s*", re.I)
_HEADING = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*\s+)?(?:abstract|introduction|background|method|"
    r"methods|study design|results?|discussion|interpretation|limitations?|"
    r"conclusion|reproducibility summary|references|appendix)\s*:??\s*$",
    re.I,
)
_METADATA = re.compile(
    r"^\s*(?:document type|version|study id|doi|received|accepted|published|"
    r"copyright|keywords?)\s*:",
    re.I,
)
_BOILERPLATE = re.compile(
    r"\b(?:not a real (?:research )?publication|not empirical findings|"
    r"not cited as a scientific publication|should not be interpreted as evidence|"
    r"no human.subject participants|no external validation dataset)\b",
    re.I,
)
_PAGE_FOOTER = re.compile(r"\bpage\s+\d+\s*$", re.I)
_CONJOINED = re.compile(
    r"\s*,?\s+(?:while|whereas)\s+(?=(?:configuration|config|model|method|system)\s+[A-Z0-9])",
    re.I,
)


@lru_cache(maxsize=1)
def load_nlp():
    """Load the pinned English sentence model or a deterministic blank sentencizer."""
    import spacy

    try:
        return spacy.load("en_core_web_sm", disable=["ner", "lemmatizer"])
    except OSError:
        nlp = spacy.blank("en")
        nlp.add_pipe("sentencizer")
        return nlp


def extractor_model_version() -> str:
    """Describe the sentence model actually active in this process."""
    nlp = load_nlp()
    name = str(nlp.meta.get("name", ""))
    version = str(nlp.meta.get("version", ""))
    if name and name != "pipeline":
        return f"spacy/{name}@{version or 'unknown'}"
    return "spacy/blank-en-sentencizer"


def extract_claims(chunks: list[EvidenceChunk], file_hash: str) -> list[Claim]:
    """Extract numeric assertions while retaining their paragraph offsets and anchors.

    Explicit ``Claim C<n>.`` annotations take precedence when a document supplies them.
    Otherwise, numeric factual sentences are selected with conservative heading and boilerplate
    filters. The confidence field is a structural extraction reliability rubric, not truth
    probability or empirical calibration.
    """
    paragraph_chunks = [
        chunk for chunk in chunks if chunk.anchor.kind is AnchorKind.PARAGRAPH
    ]
    labelled = [
        (chunk, match.start(), match.end(), _labelled_claim_text(chunk.text, match))
        for chunk in paragraph_chunks
        for match in [_CLAIM_MARKER.search(chunk.text)]
        if match is not None
    ]
    candidates: list[tuple[EvidenceChunk, int, str]] = []

    if labelled:
        for chunk, _start, end, text in labelled:
            if text:
                candidates.extend(_sentences(chunk, text, end))
    else:
        for chunk in paragraph_chunks:
            if _HEADING.fullmatch(chunk.text) or _METADATA.match(chunk.text):
                continue
            if _PAGE_FOOTER.search(chunk.text) or _BOILERPLATE.search(chunk.text):
                continue
            for sentence_chunk, offset, sentence in _sentences(chunk, chunk.text, 0):
                for assertion, assertion_offset in _split_independent_comparisons(sentence, offset):
                    cleaned = assertion.strip()
                    leading = len(assertion) - len(assertion.lstrip())
                    candidates.append((sentence_chunk, assertion_offset + leading, cleaned))

    claims: list[Claim] = []
    seen: set[tuple[str, str]] = set()
    for chunk, start, text in candidates:
        text = text.strip()
        if not text or _HEADING.fullmatch(text) or _METADATA.match(text):
            continue
        if _PAGE_FOOTER.search(text) or _BOILERPLATE.search(text) or not _ASSERTION.search(text):
            continue
        slots = parse_all_numeric_slots(
            text,
            SlotContext(anchor_id=chunk.anchor.anchor_id),
        )
        if not slots:
            continue
        comparative = bool(_COMPARATIVE.search(text)) or any(
            slot.difference_kind is not None for slot in slots
        )
        if not (
            any(slot.metric for slot in slots)
            or comparative
            or re.search(r"\b(?:table|tab\.)\s*\d+\b", text, re.I)
        ):
            continue

        key = (chunk.anchor.anchor_id, re.sub(r"\W+", " ", text.casefold()).strip())
        if key in seen:
            continue
        seen.add(key)
        claim_end = start + len(text)
        claim_type = ClaimType.COMPARATIVE if comparative else ClaimType.QUANTITATIVE
        claims.append(
            Claim(
                claim_id=stable_uuid(
                    "claim", file_hash, chunk.anchor.anchor_id, start, claim_end, EXTRACTOR_VERSION
                ),
                document_id=chunk.document_id,
                claim_text=text,
                claim_type=claim_type,
                source_anchor_id=chunk.anchor.anchor_id,
                char_start=start,
                char_end=claim_end,
                numeric_slots=slots,
                extraction_method=EXTRACTOR_VERSION,
                extraction_confidence=_confidence(text, slots, chunk),
                low_quality=chunk.anchor.low_quality,
            )
        )
    return sorted(claims, key=lambda claim: (claim.source_anchor_id, claim.char_start))


def _labelled_claim_text(text: str, marker: re.Match[str]) -> str:
    """Return the assertion after its synthetic claim label."""
    return text[marker.end():].strip()


def _sentences(
    chunk: EvidenceChunk, text: str, base_offset: int
) -> list[tuple[EvidenceChunk, int, str]]:
    """Split a text span into sentence candidates with source-chunk offsets."""
    return [
        (chunk, base_offset + sentence.start_char, text[sentence.start_char:sentence.end_char])
        for sentence in load_nlp()(text).sents
        if text[sentence.start_char:sentence.end_char].strip()
    ]


def _split_independent_comparisons(
    sentence: str, offset: int
) -> Iterable[tuple[str, int]]:
    """Separate two explicit configuration assertions joined by a contrastive clause."""
    parts = _CONJOINED.split(sentence, maxsplit=1)
    if len(parts) == 1:
        yield sentence, offset
        return
    left, right = parts
    left_slots = parse_all_numeric_slots(left)
    right_slots = parse_all_numeric_slots(right)
    if left_slots and right_slots and _ASSERTION.search(left) and _ASSERTION.search(right):
        yield left, offset
        yield right, offset + sentence.find(right)
        return
    yield sentence, offset


def _confidence(text: str, slots, chunk: EvidenceChunk) -> float:
    """Score observable extraction structure; this is not a calibrated truth probability."""
    context_coverage = sum(
        bool(slot.metric or slot.entity or slot.unit or slot.denominator or slot.comparison_basis)
        for slot in slots
    ) / len(slots)
    features = (
        text[:1].isupper(),
        text.rstrip().endswith((".", "?", "!")),
        bool(_ASSERTION.search(text)),
        any(slot.metric for slot in slots),
        context_coverage,
        not chunk.anchor.low_quality,
    )
    return round(sum(float(feature) for feature in features) / len(features), 2)
