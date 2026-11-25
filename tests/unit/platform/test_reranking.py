"""Tests for lazy local CPU reranking and ordered relevance scores."""

import math
import sys
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from domain.schemas import AnchorKind, Claim, ClaimType, EvidenceChunk, SourceAnchor
from worker.orchestration.reranking import (
    RERANKER_MODEL_ID,
    RERANKER_MODEL_REVISION,
    LocalCPUReranker,
    RerankerInferenceError,
)


class FakeCrossEncoder:
    """Capture model pair calls and return deterministic raw ranking logits."""

    def __init__(self, logits: list[float]) -> None:
        self.logits = logits
        self.pairs: list[tuple[str, str]] = []
        self.options: dict[str, object] = {}

    def predict(self, pairs: list[tuple[str, str]], **kwargs: object) -> list[float]:
        self.pairs = pairs
        self.options = kwargs
        return self.logits


def _mock_torch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Supply only the activation interface; tests never load PyTorch or model weights."""
    monkeypatch.setitem(
        sys.modules,
        "torch",
        SimpleNamespace(nn=SimpleNamespace(Identity=lambda: object())),
    )


def _claim() -> Claim:
    """Build a claim query for reranker pair-order assertions."""
    document_id = uuid4()
    return Claim(
        claim_id=uuid4(),
        document_id=document_id,
        claim_text="The sample has 40 participants.",
        claim_type=ClaimType.QUANTITATIVE,
        source_anchor_id="claim-anchor",
        char_start=0,
        char_end=32,
        extraction_method="test",
        extraction_confidence=0.9,
    )


def _evidence(document_id: UUID, text: str, caption: str | None = None) -> EvidenceChunk:
    """Build a distinct evidence source with its own persisted provenance identity."""
    anchor = SourceAnchor(
        anchor_id=f"anchor-{document_id}",
        document_id=document_id,
        kind=AnchorKind.PARAGRAPH,
        extraction_method="test",
        parser_version="test-v1",
    )
    return EvidenceChunk(
        chunk_id=uuid4(),
        document_id=document_id,
        anchor=anchor,
        text=text,
        caption=caption,
    )


def test_model_load_is_lazy_pinned_cpu_and_returns_ordered_sigmoid_scores(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No model loads at construction; inference uses the fixed revision and CPU only."""
    model = FakeCrossEncoder([2.0, -2.0])
    arguments: dict[str, object] = {}

    def construct(model_id: str, **kwargs: object) -> FakeCrossEncoder:
        arguments.update(model_id=model_id, **kwargs)
        return model

    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        SimpleNamespace(CrossEncoder=construct),
    )
    identity = object()
    monkeypatch.setitem(
        sys.modules,
        "torch",
        SimpleNamespace(nn=SimpleNamespace(Identity=lambda: identity)),
    )
    reranker = LocalCPUReranker(batch_size=2)
    assert arguments == {}

    claim = _claim()
    first = _evidence(uuid4(), "A cohort contained forty participants.", "Table 1")
    second = _evidence(uuid4(), "The experiment measured model accuracy.")
    scores = reranker.score_pairs(claim, [first, second])

    assert arguments == {
        "model_id": RERANKER_MODEL_ID,
        "revision": RERANKER_MODEL_REVISION,
        "device": "cpu",
    }
    assert model.pairs == [
        (claim.claim_text, "A cohort contained forty participants.\nCaption: Table 1"),
        (claim.claim_text, "The experiment measured model accuracy."),
    ]
    assert model.options["activation_fn"] is identity
    assert scores == pytest.approx(
        [1 / (1 + math.exp(-2)), 1 / (1 + math.exp(2))]
    )
    assert scores[0] > scores[1]


def test_empty_evidence_does_not_load_model() -> None:
    """No candidate evidence returns no score and needs no model artifacts."""
    assert LocalCPUReranker(batch_size=2).score_pairs(_claim(), []) == []


def test_missing_scores_and_model_failures_raise_specific_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bad output count and inference failures never silently become retrieval scores."""
    _mock_torch(monkeypatch)
    evidence = [_evidence(uuid4(), "first"), _evidence(uuid4(), "second")]
    missing = LocalCPUReranker(batch_size=2, model=FakeCrossEncoder([1.0]))
    with pytest.raises(RerankerInferenceError, match="wrong number"):
        missing.score_pairs(_claim(), evidence)

    class BrokenModel:
        def predict(self, _pairs: object, **_kwargs: object) -> list[float]:
            raise RuntimeError("private source text")

    broken = LocalCPUReranker(batch_size=1, model=BrokenModel())
    with pytest.raises(RerankerInferenceError, match="inference failed"):
        broken.score_pairs(_claim(), evidence[:1])


def test_non_finite_logits_fail_instead_of_returning_invalid_scores(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NaN and infinite logits cannot cross the policy score boundary."""
    _mock_torch(monkeypatch)
    reranker = LocalCPUReranker(batch_size=1, model=FakeCrossEncoder([float("nan")]))

    with pytest.raises(RerankerInferenceError, match="non-finite"):
        reranker.score_pairs(_claim(), [_evidence(uuid4(), "source")])
