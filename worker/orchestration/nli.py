"""Pinned local CPU NLI inference for retrieved claim-evidence pairs."""

from __future__ import annotations

import math
from functools import lru_cache
from typing import Any, Protocol, Sequence

from domain.entities import NLIClassification, NLILabel
from domain.schemas import Claim, EvidenceChunk
from eg_common.settings import get_settings

NLI_MODEL_ID = "cross-encoder/nli-MiniLM2-L6-H768"
NLI_MODEL_REVISION = "b95119ce93d3e065de6214e38cd4a97b0f2f2c6d"
_LABELS = (NLILabel.CONTRADICTION, NLILabel.ENTAILMENT, NLILabel.NEUTRAL)


class NLIInferenceError(RuntimeError):
    """The pinned local model failed or returned invalid class scores."""


class NLIService(Protocol):
    """Classify retrieved claim-evidence pairs without hosted services."""

    def classify_pairs(
        self, pairs: Sequence[tuple[str, str]]
    ) -> list[NLIClassification]:
        """Return one three-way distribution per premise-hypothesis pair."""


class LocalCPUNLIService:
    """Lazily run the approved CrossEncoder at its immutable model revision."""

    def __init__(self, batch_size: int, model: Any | None = None) -> None:
        """Set inference batch size and optionally accept a test double."""
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        self._batch_size = batch_size
        self._model = model

    def classify_pairs(
        self, pairs: Sequence[tuple[str, str]]
    ) -> list[NLIClassification]:
        """Infer normalized contradiction, entailment and neutral scores on CPU."""
        if not pairs:
            return []
        model = self._model or self._load_model()
        try:
            raw = model.predict(
                list(pairs),
                batch_size=self._batch_size,
                show_progress_bar=False,
                convert_to_numpy=True,
            )
            rows = raw.tolist() if hasattr(raw, "tolist") else raw
            if len(pairs) == 1 and rows and isinstance(rows[0], (float, int)):
                rows = [rows]
            if len(rows) != len(pairs):
                raise ValueError("model returned the wrong number of pair scores")
            label_indexes = self._label_indexes(model)
            return [_classification_from_logits(row, label_indexes) for row in rows]
        except NLIInferenceError:
            raise
        except Exception as exc:
            raise NLIInferenceError("local NLI inference failed") from exc

    @staticmethod
    def _load_model() -> Any:
        """Load only the approved model revision and explicitly select CPU."""
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as exc:
            raise NLIInferenceError(
                "sentence-transformers runtime dependency is unavailable"
            ) from exc
        try:
            return CrossEncoder(
                NLI_MODEL_ID,
                revision=NLI_MODEL_REVISION,
                device="cpu",
            )
        except Exception as exc:
            raise NLIInferenceError("approved local NLI model could not load") from exc

    @staticmethod
    def _label_indexes(model: Any) -> dict[NLILabel, int]:
        """Validate the pinned model's label mapping or use its documented ordering."""
        config = getattr(getattr(model, "model", None), "config", None)
        id_to_label = getattr(config, "id2label", None)
        if id_to_label is None:
            return {label: index for index, label in enumerate(_LABELS)}
        try:
            mapping = {
                NLILabel(str(label).casefold()): int(index)
                for index, label in id_to_label.items()
            }
        except ValueError as exc:
            raise NLIInferenceError("pinned NLI model has unexpected labels") from exc
        if set(mapping) != set(_LABELS):
            raise NLIInferenceError("pinned NLI model has an unexpected label mapping")
        return mapping


@lru_cache(maxsize=1)
def get_nli_service() -> NLIService:
    """Return the lazy local CPU service configured for the worker."""

    return LocalCPUNLIService(get_settings().nli_batch_size)


def classify_claim_evidence(
    claim: Claim,
    evidence: Sequence[EvidenceChunk],
    *,
    service: NLIService | None = None,
) -> list[NLIClassification]:
    """Classify each retrieved chunk as premise against the original claim hypothesis."""
    if not evidence:
        return []
    classifier = service or get_nli_service()
    pairs = [(_evidence_context(chunk), claim.claim_text) for chunk in evidence]
    results = classifier.classify_pairs(pairs)
    if len(results) != len(pairs):
        raise NLIInferenceError("NLI service returned the wrong number of pair results")
    for result in results:
        scores = (
            result.contradiction_score,
            result.entailment_score,
            result.neutral_score,
        )
        if any(not math.isfinite(value) or not 0 <= value <= 1 for value in scores):
            raise NLIInferenceError("NLI scores must be finite values between zero and one")
        if not math.isclose(sum(scores), 1.0, rel_tol=1e-5, abs_tol=1e-5):
            raise NLIInferenceError("NLI class scores must sum to one")
    return results


def _evidence_context(chunk: EvidenceChunk) -> str:
    """Include table context in the model premise while preserving the source object."""
    parts = [chunk.text]
    if chunk.caption:
        parts.append(f"Caption: {chunk.caption}")
    if chunk.headers:
        parts.append("Headers: " + " | ".join(chunk.headers))
    if chunk.cells:
        cell_context = " | ".join(
            f"{key}: {value}" for key, value in chunk.cells.items()
        )
        parts.append("Cells: " + cell_context)
    return "\n".join(parts)


def _classification_from_logits(
    logits: Sequence[float], label_indexes: dict[NLILabel, int]
) -> NLIClassification:
    """Convert three model logits to a stable softmax distribution."""
    if len(logits) != 3:
        raise NLIInferenceError("NLI model must return exactly three class logits")
    values = [float(value) for value in logits]
    if any(not math.isfinite(value) for value in values):
        raise NLIInferenceError("NLI logits must be finite")
    maximum = max(values)
    exponentials = [math.exp(value - maximum) for value in values]
    denominator = sum(exponentials)
    scores = {
        label: exponentials[index] / denominator
        for label, index in label_indexes.items()
    }
    label = max(scores, key=scores.__getitem__)
    return NLIClassification(
        label=label,
        contradiction_score=scores[NLILabel.CONTRADICTION],
        entailment_score=scores[NLILabel.ENTAILMENT],
        neutral_score=scores[NLILabel.NEUTRAL],
    )
