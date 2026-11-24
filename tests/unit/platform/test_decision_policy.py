"""Focused tests for framework policy order, abstention, and numeric precedence."""

import pytest

from domain.entities import NLIClassification, NLILabel, VerdictStatus
from domain.schemas import CheckResult
from worker.orchestration.decision_policy import (
    DecisionPolicyInputError,
    DecisionThresholds,
    decide_verdict,
)
from worker.verification.numeric import SlotVerification


def _thresholds(**overrides: float | None) -> DecisionThresholds:
    """Return synthetic test calibration values; runtime defaults remain unset."""
    values: dict[str, float | None] = {
        "tau_ext": 0.5,
        "tau_ret": 0.5,
        "tau_e": 0.8,
        "tau_c": 0.8,
    }
    values.update(overrides)
    return DecisionThresholds(**values)


def _slot(index: int, result: CheckResult) -> SlotVerification:
    """Build one B numeric outcome for policy-only branch testing."""
    return SlotVerification(index, result, "test", [])


def _nli(
    label: NLILabel,
    contradiction: float,
    entailment: float,
    neutral: float,
) -> NLIClassification:
    """Build one normalized synthetic NLI distribution."""
    return NLIClassification(label, contradiction, entailment, neutral)


def _decide(**overrides: object):
    """Apply defaults for the common high-quality, retrieved-evidence case."""
    values: dict[str, object] = {
        "extraction_confidence": 0.9,
        "claim_low_quality": False,
        "evidence_low_quality": False,
        "numeric_results": [],
        "nli_results": [_nli(NLILabel.NEUTRAL, 0.05, 0.05, 0.9)],
        "best_reranker_score": 0.9,
        "thresholds": _thresholds(),
    }
    values.update(overrides)
    return decide_verdict(**values)  # type: ignore[arg-type]


def test_threshold_absence_and_low_quality_abstain_before_numeric_rules() -> None:
    """Rule 1 requires calibrated extraction threshold and source quality."""
    missing = _decide(
        thresholds=_thresholds(tau_ext=None),
        numeric_results=[_slot(0, CheckResult.MISMATCH)],
    )
    low_quality = _decide(
        claim_low_quality=True,
        numeric_results=[_slot(0, CheckResult.MISMATCH)],
    )
    low_quality_evidence = _decide(evidence_low_quality=True)
    below_threshold = _decide(extraction_confidence=0.4)

    assert missing.status is VerdictStatus.NEEDS_REVIEW
    assert missing.reason == "threshold_unavailable:tau_ext"
    assert low_quality.status is VerdictStatus.NEEDS_REVIEW
    assert low_quality.reason == "low_quality_source"
    assert low_quality_evidence.reason == "low_quality_source"
    assert below_threshold.status is VerdictStatus.NEEDS_REVIEW
    assert below_threshold.reason == "extraction_confidence_below_threshold"


def test_numeric_mismatch_precedes_incomparable_and_nli_conflict() -> None:
    """Any definite mismatch contradicts even when another slot is incomparable."""
    verdict = _decide(
        numeric_results=[
            _slot(0, CheckResult.MATCH),
            _slot(1, CheckResult.INCOMPARABLE),
            _slot(2, CheckResult.MISMATCH),
        ],
        nli_results=[_nli(NLILabel.ENTAILMENT, 0.9, 0.05, 0.05)],
    )

    assert verdict.status is VerdictStatus.CONTRADICTED
    assert verdict.reason == "numeric_mismatch"
    assert "mismatching_slots:2" in verdict.explanation


def test_incomparable_numeric_slots_need_review_when_no_mismatch_exists() -> None:
    """An incomparable required slot is not promoted to a numeric mismatch."""
    verdict = _decide(
        numeric_results=[
            _slot(0, CheckResult.MATCH),
            _slot(1, CheckResult.INCOMPARABLE),
        ]
    )

    assert verdict.status is VerdictStatus.NEEDS_REVIEW
    assert verdict.reason == "numeric_slots_incomparable"


def test_reranker_rule_waits_for_reranker_and_uses_only_its_threshold() -> None:
    """Rule 4 abstains without a reranker and uses configured reranker scores only."""
    unavailable = _decide(best_reranker_score=None)
    threshold_missing = _decide(thresholds=_thresholds(tau_ret=None))
    below = _decide(best_reranker_score=0.4)

    assert unavailable.reason == "reranker_unavailable"
    assert threshold_missing.reason == "threshold_unavailable:tau_ret"
    assert below.status is VerdictStatus.UNSUPPORTED
    assert below.reason == "reranker_score_below_threshold"


def test_numeric_match_with_conflicting_nli_requires_review() -> None:
    """Rule 5 records conflict between a numeric match and confident NLI contradiction."""
    verdict = _decide(
        numeric_results=[_slot(0, CheckResult.MATCH)],
        nli_results=[_nli(NLILabel.CONTRADICTION, 0.9, 0.05, 0.05)],
    )

    assert verdict.status is VerdictStatus.NEEDS_REVIEW
    assert verdict.reason == "numeric_semantic_conflict"


def test_all_comparable_numeric_matches_support_when_nli_is_neutral() -> None:
    """Rule 6 supports matched numeric slots when NLI is neutral or non-conflicting."""
    verdict = _decide(
        numeric_results=[
            _slot(0, CheckResult.MATCH),
            _slot(1, CheckResult.NOT_APPLICABLE),
        ]
    )

    assert verdict.status is VerdictStatus.SUPPORTED
    assert verdict.reason == "numeric_match"


def test_mixed_multi_part_outcomes_are_partially_supported() -> None:
    """Rule 7 retains partial status when supplied part decisions are mixed."""
    verdict = _decide(
        nli_results=[],
        part_outcomes=[VerdictStatus.SUPPORTED, VerdictStatus.NEEDS_REVIEW],
    )

    assert verdict.status is VerdictStatus.PARTIALLY_SUPPORTED
    assert verdict.reason == "mixed_part_support"


def test_non_numeric_entailment_and_contradiction_require_calibrated_thresholds() -> None:
    """Rules 8 and 9 use the matching configured NLI class thresholds."""
    entailment = _decide(
        numeric_results=[],
        nli_results=[_nli(NLILabel.ENTAILMENT, 0.05, 0.9, 0.05)],
    )
    contradiction = _decide(
        numeric_results=[],
        nli_results=[_nli(NLILabel.CONTRADICTION, 0.9, 0.05, 0.05)],
    )
    missing_entailment = _decide(
        nli_results=[_nli(NLILabel.ENTAILMENT, 0.05, 0.9, 0.05)],
        thresholds=_thresholds(tau_e=None),
    )

    assert entailment.status is VerdictStatus.SUPPORTED
    assert contradiction.status is VerdictStatus.CONTRADICTED
    assert missing_entailment.reason == "threshold_unavailable:tau_e"


def test_neutral_nli_is_unsupported_and_weak_non_neutral_nli_abstains() -> None:
    """Rule 10 distinguishes neutral evidence from below-threshold non-neutral scores."""
    neutral = _decide()
    weak_entailment = _decide(
        nli_results=[_nli(NLILabel.ENTAILMENT, 0.1, 0.6, 0.3)]
    )

    assert neutral.status is VerdictStatus.UNSUPPORTED
    assert weak_entailment.status is VerdictStatus.NEEDS_REVIEW
    assert weak_entailment.reason == "nli_below_calibrated_threshold"


def test_malformed_confidence_is_rejected() -> None:
    """The policy does not quietly compare NaN or out-of-range values."""
    with pytest.raises(DecisionPolicyInputError):
        _decide(extraction_confidence=float("nan"))


def test_thresholds_do_not_supply_implicit_runtime_defaults() -> None:
    """Uncalibrated production settings remain unset and produce Needs Review."""
    verdict = _decide(thresholds=DecisionThresholds())

    assert verdict.status is VerdictStatus.NEEDS_REVIEW
    assert verdict.confidence is None
