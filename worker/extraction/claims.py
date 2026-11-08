
import re
from functools import lru_cache

from domain.schemas import AnchorKind, Claim, ClaimType, EvidenceChunk
from worker.ingestion.anchors import stable_uuid
from .slots import SlotContext, parse_all_numeric_slots


EXTRACTOR_VERSION = "rules-1"

# Words that indicate a comparison or change.
_COMPARE = re.compile(
    r"\b(outperform\w*|improv\w*|higher|lower|better|worse|than|"
    r"versus|vs\.?|increase\w*|decrease\w*)\b",
    re.I,
)

# References to tables in the document.
_TABLE_REF = re.compile(r"\b(Table|Tab\.)\s*\d+", re.I)


@lru_cache(maxsize=1)
def load_nlp():
    """
    Load spaCy for sentence segmentation.

    Prefer the English model. If it is unavailable,
    use a blank English pipeline with a sentencizer.
    """
    import spacy

    try:
        return spacy.load(
            "en_core_web_sm",
            disable=["ner", "lemmatizer"],
        )
    except OSError:
        nlp = spacy.blank("en")
        nlp.add_pipe("sentencizer")
        return nlp


def extract_claims(
    chunks: list[EvidenceChunk],
    file_hash: str,
) -> list[Claim]:
    """
    Extract quantitative and comparative claims from paragraph chunks.

    Table and CSV chunks are deliberately skipped because they
    are evidence sources, not claim sources.
    """
    nlp = load_nlp()
    claims = []

    for ch in chunks:

        # Only paragraph chunks can be claim sources.
        if ch.anchor.kind != AnchorKind.PARAGRAPH:
            continue

        # Split the paragraph into sentences.
        for sent in nlp(ch.text).sents:

            raw = ch.text[sent.start_char:sent.end_char]
            text = raw.strip()

            if not text:
                continue

            # Calculate the sentence's actual position in the paragraph.
            leading_spaces = len(raw) - len(raw.lstrip())
            start = sent.start_char + leading_spaces
            end = start + len(text)

            # Extract all numeric mentions from this sentence.
            slots = parse_all_numeric_slots(
                text,
                SlotContext(
                    anchor_id=ch.anchor.anchor_id
                ),
            )

            # No numeric mentions means no claim for this extractor.
            if not slots:
                continue

            comparative = bool(_COMPARE.search(text))
            table_reference = bool(_TABLE_REF.search(text))

            # Keep sentences with a recognised metric,
            # comparative cue, or table reference.
            if not (
                any(slot.metric for slot in slots)
                or comparative
                or table_reference
            ):
                continue

            # Deterministic rule-based confidence score.
            confidence = (
                0.4
                + 0.2 * any(slot.metric for slot in slots)
                + 0.2 * any(slot.entity for slot in slots)
                + 0.1 * any(slot.unit for slot in slots)
                + 0.1 * (comparative or table_reference)
            )

            # Generate a stable claim ID.
            claim_id = stable_uuid(
                "claim",
                file_hash,
                ch.anchor.anchor_id,
                start,
                end,
                EXTRACTOR_VERSION,
            )

            claim = Claim(
                claim_id=claim_id,
                document_id=ch.document_id,
                claim_text=text,
                claim_type=(
                    ClaimType.COMPARATIVE
                    if comparative
                    else ClaimType.QUANTITATIVE
                ),
                source_anchor_id=ch.anchor.anchor_id,
                char_start=start,
                char_end=end,
                numeric_slots=slots,
                extraction_method=EXTRACTOR_VERSION,
                extraction_confidence=round(confidence, 2),
                low_quality=ch.anchor.low_quality,
            )

            claims.append(claim)

    # Stable output order across repeated runs.
    return sorted(
        claims,
        key=lambda claim: (
            claim.source_anchor_id,
            claim.char_start,
        ),
    )
