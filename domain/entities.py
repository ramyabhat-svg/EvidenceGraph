"""Platform-owned result entities that do not alter the shared Pydantic schemas."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from uuid import UUID


class NLILabel(str, Enum):
    """Frozen labels emitted by the approved three-way NLI model."""

    CONTRADICTION = "contradiction"
    ENTAILMENT = "entailment"
    NEUTRAL = "neutral"


class VerdictStatus(str, Enum):
    """Claim-level statuses defined by the EvidenceGraph framework."""

    SUPPORTED = "Supported"
    PARTIALLY_SUPPORTED = "Partially Supported"
    CONTRADICTED = "Contradicted"
    UNSUPPORTED = "Unsupported"
    NEEDS_REVIEW = "Needs Review"


@dataclass(frozen=True)
class NLIClassification:
    """One claim-evidence NLI distribution with the predicted label."""

    label: NLILabel
    contradiction_score: float
    entailment_score: float
    neutral_score: float


@dataclass(frozen=True)
class Verdict:
    """Final policy output with a stable reason and optional model confidence."""

    status: VerdictStatus
    confidence: float | None
    reason: str
    explanation: tuple[str, ...]


@dataclass(frozen=True)
class PersistedNLIResult:
    """NLI output paired with its platform evidence identity for persistence."""

    evidence_chunk_id: UUID
    classification: NLIClassification


@dataclass(frozen=True)
class PersistedVerdict:
    """One persisted verdict with its run identity and evidence provenance IDs."""

    run_id: UUID
    claim_id: UUID
    verdict: Verdict
    policy_version: str
    evidence_chunk_ids: tuple[UUID, ...]
