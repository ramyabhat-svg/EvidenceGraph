"""Pinned local CPU reranker and A-owned claim-evidence ranking contract."""

from __future__ import annotations

import math
from functools import lru_cache
from typing import Any, Protocol, Sequence

from domain.schemas import Claim, EvidenceChunk
from eg_common.settings import get_settings

RERANKER_MODEL_ID = "cross-encoder/ms-marco-MiniLM-L6-v2"
RERANKER_MODEL_REVISION = "233902d25c440f23af6f7d6e94d2946bac0bee0a"


class RerankerInferenceError(RuntimeError):
    """The pinned local reranker failed or returned invalid pair scores."""


class EvidenceReranker(Protocol):
    """Score retrieved claim-evidence pairs independently of the retrieval ranker."""

    def score_pairs(
        self,
        claim: Claim,
        evidence: Sequence[EvidenceChunk],
    ) -> list[float]:
        """Return one [0, 1] relevance score per evidence item, in input order.

        Scores are sigmoid-transformed ranking logits, not calibrated probabilities.
        """


class LocalCPUReranker:
    """Lazily run the pinned MS MARCO CrossEncoder on CPU."""

    def __init__(self, batch_size: int, model: Any | None = None) -> None:
        """Configure inference batching and optionally accept a test model double."""
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        self._batch_size = batch_size
        self._model = model

    def score_pairs(
        self,
        claim: Claim,
        evidence: Sequence[EvidenceChunk],
    ) -> list[float]:
        """Return monotonic sigmoid relevance scores in evidence input order."""
        if not evidence:
            return []
        model = self._model or self._load_model()
        pairs = [(claim.claim_text, _evidence_text(chunk)) for chunk in evidence]
        try:
            import torch

            raw = model.predict(
                pairs,
                batch_size=self._batch_size,
                show_progress_bar=False,
                convert_to_numpy=True,
                activation_fn=torch.nn.Identity(),
            )
            values = raw.tolist() if hasattr(raw, "tolist") else raw
            if isinstance(values, (float, int)):
                values = [values]
            logits = [
                float(value[0] if isinstance(value, (list, tuple)) else value)
                for value in values
            ]
            if len(logits) != len(evidence):
                raise RerankerInferenceError(
                    "reranker returned the wrong number of pair scores"
                )
            if any(not math.isfinite(logit) for logit in logits):
                raise RerankerInferenceError("reranker returned a non-finite ranking logit")
            return [_sigmoid(logit) for logit in logits]
        except RerankerInferenceError:
            raise
        except Exception as exc:
            raise RerankerInferenceError("local reranker inference failed") from exc

    @staticmethod
    def _load_model() -> Any:
        """Load only the approved model revision and explicitly select the CPU device."""
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as exc:
            raise RerankerInferenceError(
                "sentence-transformers runtime dependency is unavailable"
            ) from exc
        try:
            return CrossEncoder(
                RERANKER_MODEL_ID,
                revision=RERANKER_MODEL_REVISION,
                device="cpu",
            )
        except Exception as exc:
            raise RerankerInferenceError("approved local reranker model could not load") from exc


@lru_cache(maxsize=1)
def get_reranker_service() -> EvidenceReranker:
    """Return the lazy CPU reranker configured with the worker batch size."""
    return LocalCPUReranker(get_settings().reranker_batch_size)


def _sigmoid(logit: float) -> float:
    """Map an unbounded ranking logit monotonically to the configured [0, 1] score range."""
    if logit >= 0:
        return 1.0 / (1.0 + math.exp(-logit))
    exponential = math.exp(logit)
    return exponential / (1.0 + exponential)


def _evidence_text(chunk: EvidenceChunk) -> str:
    """Include table metadata as passage context without changing persisted evidence."""
    sections = [chunk.text]
    if chunk.caption:
        sections.append(f"Caption: {chunk.caption}")
    if chunk.headers:
        sections.append("Headers: " + " | ".join(chunk.headers))
    if chunk.cells:
        cells = " | ".join(f"{key}: {value}" for key, value in chunk.cells.items())
        sections.append("Cells: " + cells)
    return "\n".join(sections)
