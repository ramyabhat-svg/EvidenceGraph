"""Versioned ordered decision policy with explicit, calibrated threshold inputs."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from domain.entities import NLIClassification, NLILabel, Verdict, VerdictStatus
from domain.schemas import CheckResult
from eg_common.settings import Settings
from worker.verification.numeric import SlotVerification

POLICY_VERSION = "decision-policy-v2"


class DecisionPolicyInputError(ValueError):
    """The policy received malformed confidence, score, or component results."""


@dataclass(frozen=True)
class DecisionThresholds:
    """Thresholds calibrated on the development split; unset values stay unknown."""

    tau_ext: float | None = None
    tau_ret: float | None = None
    tau_e: float | None = None
    tau_c: float | None = None

    def __post_init__(self) -> None:
        """Reject invalid configured thresholds without supplying defaults."""
        for name, value in (
            ("tau_ext", self.tau_ext),
            ("tau_ret", self.tau_ret),
            ("tau_e", self.tau_e),
            ("tau_c", self.tau_c),
        ):
            if value is not None and (not math.isfinite(value) or not 0 <= value <= 1):
                raise ValueError(f"{name} must be between zero and one")

    @classmethod
    def from_settings(cls, settings: Settings) -> DecisionThresholds:
        """Read calibrated thresholds from application settings without fallback values."""
        return cls(
            tau_ext=settings.policy_tau_ext,
            tau_ret=settings.policy_tau_ret,
            tau_e=settings.policy_tau_e,
            tau_c=settings.policy_tau_c,
        )


def decide_verdict(
    *,
    extraction_confidence: float,
    claim_low_quality: bool,
    evidence_low_quality: bool,
    numeric_results: Sequence[SlotVerification],
    nli_results: Sequence[NLIClassification],
    best_reranker_score: float | None,
    thresholds: DecisionThresholds,
    part_outcomes: Sequence[VerdictStatus] = (),
    retrieval_empty: bool = False,
) -> Verdict:
    """Apply the ordered policy in order and abstain when required inputs are unavailable."""
    _validate_probability("extraction_confidence", extraction_confidence)
    if best_reranker_score is not None:
        _validate_probability("best_reranker_score", best_reranker_score)
    for result in nli_results:
        for score in (
            result.contradiction_score,
            result.entailment_score,
            result.neutral_score,
        ):
            _validate_probability("nli_score", score)

    if thresholds.tau_ext is None:
        return _needs_review("threshold_unavailable:tau_ext")
    if claim_low_quality or evidence_low_quality:
        return _needs_review("low_quality_source")
    if extraction_confidence < thresholds.tau_ext:
        return _needs_review("extraction_confidence_below_threshold")

    if retrieval_empty:
        return Verdict(
            status=VerdictStatus.UNSUPPORTED,
            confidence=None,
            reason="no_retrieval_candidates",
            explanation=("retrieval_completed_with_empty_results",),
        )

    numeric_status = _aggregate_numeric_results(numeric_results)
    mismatches = [
        result.slot_index
        for result in numeric_results
        if result.overall is CheckResult.MISMATCH
    ]
    if mismatches:
        return Verdict(
            status=VerdictStatus.CONTRADICTED,
            confidence=None,
            reason="numeric_mismatch",
            explanation=(
                "numeric_mismatch_takes_precedence",
                "mismatching_slots:" + ",".join(str(index) for index in mismatches),
            ),
        )
    incomparable = [
        result.slot_index
        for result in numeric_results
        if result.overall is CheckResult.INCOMPARABLE
    ]
    if incomparable:
        return Verdict(
            status=VerdictStatus.NEEDS_REVIEW,
            confidence=None,
            reason="numeric_slots_incomparable",
            explanation=("incomparable_slots:" + ",".join(str(i) for i in incomparable),),
        )

    if best_reranker_score is None:
        return _needs_review("reranker_unavailable")
    if thresholds.tau_ret is None:
        return _needs_review("threshold_unavailable:tau_ret")
    if best_reranker_score < thresholds.tau_ret:
        return Verdict(
            status=VerdictStatus.UNSUPPORTED,
            confidence=best_reranker_score,
            reason="reranker_score_below_threshold",
            explanation=("no_relevant_evidence_by_reranker",),
        )

    if _mixed_part_outcomes(part_outcomes):
        return Verdict(
            status=VerdictStatus.PARTIALLY_SUPPORTED,
            confidence=None,
            reason="mixed_part_support",
            explanation=("claim_parts_have_mixed_support",),
        )

    if numeric_status is CheckResult.MATCH:
        if not nli_results:
            return _needs_review("nli_result_missing")
        if thresholds.tau_c is None:
            return _needs_review("threshold_unavailable:tau_c")
        max_contradiction = max(item.contradiction_score for item in nli_results)
        if max_contradiction >= thresholds.tau_c:
            return Verdict(
                status=VerdictStatus.NEEDS_REVIEW,
                confidence=max_contradiction,
                reason="numeric_semantic_conflict",
                explanation=("numeric_match_conflicts_with_nli_contradiction",),
            )
        max_entailment = max(item.entailment_score for item in nli_results)
        return Verdict(
            status=VerdictStatus.SUPPORTED,
            confidence=max_entailment,
            reason="numeric_match",
            explanation=("all_comparable_numeric_slots_match",),
        )

    if not nli_results:
        return _needs_review("nli_result_missing")
    max_entailment = max(item.entailment_score for item in nli_results)
    max_contradiction = max(item.contradiction_score for item in nli_results)
    entailment_met = thresholds.tau_e is not None and max_entailment >= thresholds.tau_e
    contradiction_met = (
        thresholds.tau_c is not None and max_contradiction >= thresholds.tau_c
    )
    if entailment_met and contradiction_met:
        return _needs_review("conflicting_nli_evidence")
    if entailment_met:
        if thresholds.tau_c is None:
            return _needs_review("threshold_unavailable:tau_c")
        return Verdict(
            status=VerdictStatus.SUPPORTED,
            confidence=max_entailment,
            reason="nli_entailment_threshold_met",
            explanation=("nli_entailment_exceeds_calibrated_threshold",),
        )
    if contradiction_met:
        if thresholds.tau_e is None:
            return _needs_review("threshold_unavailable:tau_e")
        return Verdict(
            status=VerdictStatus.CONTRADICTED,
            confidence=max_contradiction,
            reason="nli_contradiction_threshold_met",
            explanation=("nli_contradiction_exceeds_calibrated_threshold",),
        )

    predicted_labels = {result.label for result in nli_results}
    if NLILabel.ENTAILMENT in predicted_labels and thresholds.tau_e is None:
        return _needs_review("threshold_unavailable:tau_e")
    if NLILabel.CONTRADICTION in predicted_labels and thresholds.tau_c is None:
        return _needs_review("threshold_unavailable:tau_c")

    best_label = max(
        nli_results,
        key=lambda item: max(
            item.contradiction_score,
            item.entailment_score,
            item.neutral_score,
        ),
    ).label
    if best_label.value == "neutral":
        return Verdict(
            status=VerdictStatus.UNSUPPORTED,
            confidence=max(item.neutral_score for item in nli_results),
            reason="nli_neutral",
            explanation=("no_nli_support_or_contradiction_threshold_met",),
        )
    return _needs_review("nli_below_calibrated_threshold")


def _aggregate_numeric_results(
    results: Sequence[SlotVerification],
) -> CheckResult | None:
    """Aggregate numeric outcomes with approved mismatch-before-incomparable precedence."""
    statuses = [result.overall for result in results]
    if CheckResult.MISMATCH in statuses:
        return CheckResult.MISMATCH
    if CheckResult.INCOMPARABLE in statuses:
        return CheckResult.INCOMPARABLE
    comparable = [status for status in statuses if status is CheckResult.MATCH]
    if comparable and len(comparable) == len(
        [status for status in statuses if status is not CheckResult.NOT_APPLICABLE]
    ):
        return CheckResult.MATCH
    return None


def _mixed_part_outcomes(outcomes: Sequence[VerdictStatus]) -> bool:
    """Recognize partially supported multi-part claims after rule 7's component outcomes."""
    return (
        VerdictStatus.SUPPORTED in outcomes
        and any(
            outcome in {VerdictStatus.UNSUPPORTED, VerdictStatus.NEEDS_REVIEW}
            for outcome in outcomes
        )
    )


def _validate_probability(name: str, value: float) -> None:
    """Reject malformed confidence values before applying threshold comparisons."""
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise DecisionPolicyInputError(f"{name} must be finite and between zero and one")


def _needs_review(reason: str) -> Verdict:
    """Build an abstaining result with a stable machine-readable reason."""
    return Verdict(
        status=VerdictStatus.NEEDS_REVIEW,
        confidence=None,
        reason=reason,
        explanation=(reason,),
    )
