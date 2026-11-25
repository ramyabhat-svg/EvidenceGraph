"""Tests for pinned local NLI inference without fetching model weights."""

import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest

from domain.entities import NLIClassification, NLILabel
from domain.schemas import AnchorKind, Claim, ClaimType, EvidenceChunk, SourceAnchor
from worker.orchestration import nli


class FakeCrossEncoder:
    """Capture local model calls and return deterministic logits."""

    def __init__(self) -> None:
        self.model = SimpleNamespace(
            config=SimpleNamespace(
                id2label={
                    0: "contradiction",
                    1: "entailment",
                    2: "neutral",
                }
            )
        )
        self.pairs: list[tuple[str, str]] = []
        self.options: dict[str, object] = {}

    def predict(self, pairs: list[tuple[str, str]], **kwargs: object) -> list[list[float]]:
        self.pairs = pairs
        self.options = kwargs
        return [[0.0, 2.0, -1.0] for _ in pairs]


def _claim() -> Claim:
    """Build a test claim for evidence-pair input checks."""
    document_id = uuid4()
    return Claim(
        claim_id=uuid4(),
        document_id=document_id,
        claim_text="The model achieved high accuracy.",
        claim_type=ClaimType.CATEGORICAL,
        source_anchor_id="claim-source",
        char_start=0,
        char_end=35,
        extraction_method="test",
        extraction_confidence=0.9,
    )


def _evidence() -> EvidenceChunk:
    """Build table evidence whose row context must accompany its text."""
    document_id = uuid4()
    anchor = SourceAnchor(
        anchor_id="table-row",
        document_id=document_id,
        kind=AnchorKind.TABLE_ROW,
        extraction_method="test",
        parser_version="test-v1",
    )
    return EvidenceChunk(
        chunk_id=uuid4(),
        document_id=document_id,
        anchor=anchor,
        text="Ours 91.2",
        caption="Test set results",
        headers=["Model", "Accuracy (%)"],
        cells={"Model": "Ours", "Accuracy (%)": "91.2"},
    )


def test_model_load_is_revision_pinned_and_cpu_only_without_weight_downloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The mocked CrossEncoder sees the approved immutable revision and CPU device."""
    fake_model = FakeCrossEncoder()
    arguments: dict[str, object] = {}

    def construct(model_id: str, **kwargs: object) -> FakeCrossEncoder:
        arguments.update(model_id=model_id, **kwargs)
        return fake_model

    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        SimpleNamespace(CrossEncoder=construct),
    )
    service = nli.LocalCPUNLIService(batch_size=3)

    results = service.classify_pairs([("evidence", "claim")])

    assert arguments == {
        "model_id": nli.NLI_MODEL_ID,
        "revision": nli.NLI_MODEL_REVISION,
        "device": "cpu",
    }
    assert results[0].label is NLILabel.ENTAILMENT
    assert results[0].entailment_score == pytest.approx(0.8438, abs=0.001)
    assert fake_model.options["batch_size"] == 3


@pytest.mark.parametrize(
    ("logits", "expected"),
    [
        ([0.0, 4.0, 0.0], NLILabel.ENTAILMENT),
        ([4.0, 0.0, 0.0], NLILabel.CONTRADICTION),
        ([0.0, 0.0, 4.0], NLILabel.NEUTRAL),
    ],
)
def test_model_logits_map_to_each_canonical_nli_label(
    logits: list[float], expected: NLILabel
) -> None:
    """Contradiction, entailment, and neutral logits map through explicit model indices."""

    class FixedModel:
        model = SimpleNamespace(
            config=SimpleNamespace(
                id2label={0: "contradiction", 1: "entailment", 2: "neutral"}
            )
        )

        def predict(self, _pairs: list[tuple[str, str]], **_options: object) -> list[list[float]]:
            return [logits]

    [result] = nli.LocalCPUNLIService(batch_size=1, model=FixedModel()).classify_pairs(
        [("evidence premise", "claim hypothesis")]
    )

    assert result.label is expected
    assert sum(
        (result.contradiction_score, result.entailment_score, result.neutral_score)
    ) == pytest.approx(1.0)


def test_claim_context_and_original_claim_are_the_ordered_nli_pair() -> None:
    """Evidence context is premise and the unchanged claim is hypothesis."""
    claim, chunk = _claim(), _evidence()

    class CaptureService:
        def classify_pairs(
            self, pairs: list[tuple[str, str]]
        ) -> list[NLIClassification]:
            self.pairs = pairs
            return [NLIClassification(NLILabel.NEUTRAL, 0.1, 0.2, 0.7)]

    service = CaptureService()
    result = nli.classify_claim_evidence(claim, [chunk], service=service)

    assert result[0].label is NLILabel.NEUTRAL
    premise, hypothesis = service.pairs[0]
    assert premise.startswith(chunk.text)
    assert "Caption: Test set results" in premise
    assert "Accuracy (%): 91.2" in premise
    assert hypothesis == claim.claim_text


def test_empty_evidence_does_not_construct_the_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing evidence returns no NLI rows without touching model loading."""
    monkeypatch.setattr(
        nli,
        "get_nli_service",
        lambda: pytest.fail("no model needed for an empty pair set"),
    )

    assert nli.classify_claim_evidence(_claim(), []) == []


def test_invalid_nli_distribution_is_rejected() -> None:
    """Malformed mocked service results cannot enter policy or persistence."""

    class InvalidService:
        def classify_pairs(
            self, _pairs: list[tuple[str, str]]
        ) -> list[NLIClassification]:
            return [NLIClassification(NLILabel.ENTAILMENT, 0.2, 0.2, 0.2)]

    with pytest.raises(nli.NLIInferenceError, match="sum to one"):
        nli.classify_claim_evidence(_claim(), [_evidence()], service=InvalidService())
