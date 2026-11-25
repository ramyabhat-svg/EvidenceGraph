"""Run local NLI on retrieved evidence and persist framework-policy verdicts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from domain.entities import NLIClassification, PersistedNLIResult, Verdict
from domain.schemas import Claim, EvidenceChunk
from eg_common.ids import derive_uuid
from eg_common.settings import Settings, get_settings
from persistence.models import DocumentRow
from persistence.repositories import PersistenceNotFoundError, PersistenceRepository
from worker.orchestration.decision_policy import (
    POLICY_VERSION,
    DecisionThresholds,
    decide_verdict,
)
from worker.orchestration.embeddings import EmbeddingService
from worker.orchestration.nli import (
    NLI_MODEL_ID,
    NLI_MODEL_REVISION,
    NLIService,
    classify_claim_evidence,
)
from worker.orchestration.reranking import (
    RERANKER_MODEL_ID,
    RERANKER_MODEL_REVISION,
    EvidenceReranker,
    get_reranker_service,
)
from worker.orchestration.retrieval import retrieve_for_claim
from worker.orchestration.run_identity import analysis_run_id
from worker.orchestration.verification import ClaimNumericVerification
from worker.verification.numeric import SlotVerification


@dataclass(frozen=True)
class ClaimVerdictResult:
    """One persisted claim's final decision and the retrieved evidence behind it."""

    claim_id: UUID
    verdict: Verdict
    evidence: list[EvidenceChunk]


def generate_document_verdicts(
    session: Session,
    document_id: UUID,
    *,
    numeric_outputs: list[ClaimNumericVerification] | None = None,
    settings: Settings | None = None,
    embedding_service: EmbeddingService | None = None,
    nli_service: NLIService | None = None,
    reranker: EvidenceReranker | None = None,
) -> list[ClaimVerdictResult]:
    """Persist pair scores and ordered policy verdicts for every persisted claim."""
    document = session.get(DocumentRow, document_id)
    if document is None:
        raise PersistenceNotFoundError(f"document {document_id} does not exist")
    config = settings or get_settings()
    run_id = analysis_run_id(document_id, config)
    repository = PersistenceRepository(session)
    claims = repository.list_claims(document_id)
    if not claims:
        return []

    numeric_by_claim = {
        output.claim_id: output
        for output in numeric_outputs or []
    }
    results: list[ClaimVerdictResult] = []
    for claim in claims:
        claim_id = _claim_persistence_id(claim)
        numeric_output = numeric_by_claim.get(claim_id)
        ranked = (
            numeric_output.ranked_evidence
            if numeric_output is not None
            else retrieve_for_claim(
                session,
                document.project_id,
                claim,
                settings=config,
                embedding_service=embedding_service,
            )
        )
        evidence = [item.chunk for item in ranked]
        evidence_ids = [_evidence_persistence_id(item) for item in evidence]
        classifications = _classify_unpersisted_pairs(
            repository,
            run_id,
            claim_id,
            claim,
            evidence,
            evidence_ids,
            nli_service,
        )
        repository.store_nli_results(
            run_id=run_id,
            claim_id=claim_id,
            results=[
                PersistedNLIResult(evidence_chunk_id=evidence_id, classification=result)
                for evidence_id, result in zip(evidence_ids, classifications)
            ],
            model_id=NLI_MODEL_ID,
            model_revision=NLI_MODEL_REVISION,
        )

        numeric_results: list[SlotVerification] = repository.list_numeric_verifications(
            run_id,
            claim_id,
        )
        reranker_scores = _score_unpersisted_pairs(
            repository,
            run_id,
            claim_id,
            claim,
            evidence,
            evidence_ids,
            reranker,
        )
        order = sorted(
            range(len(evidence)),
            key=lambda index: (
                -reranker_scores[index],
                ranked[index].rank,
                str(evidence_ids[index]),
            ),
        )
        evidence = [evidence[index] for index in order]
        evidence_ids = [evidence_ids[index] for index in order]
        classifications = [classifications[index] for index in order]
        ranked = [ranked[index] for index in order]
        reranker_scores = [reranker_scores[index] for index in order]
        best_reranker_score = max(reranker_scores) if reranker_scores else None
        best_evidence_is_low_quality = (
            evidence[reranker_scores.index(best_reranker_score)].anchor.low_quality
            if reranker_scores and best_reranker_score is not None
            else any(chunk.anchor.low_quality for chunk in evidence)
        )
        thresholds = DecisionThresholds.from_settings(config)
        policy_nli_results = (
            [
                classification
                for classification, score in zip(classifications, reranker_scores)
                if thresholds.tau_ret is not None and score >= thresholds.tau_ret
            ]
            if thresholds.tau_ret is not None
            else classifications
        )
        verdict = decide_verdict(
            extraction_confidence=claim.extraction_confidence,
            claim_low_quality=claim.low_quality,
            evidence_low_quality=best_evidence_is_low_quality,
            numeric_results=numeric_results,
            nli_results=policy_nli_results,
            best_reranker_score=best_reranker_score,
            thresholds=thresholds,
            retrieval_empty=not evidence,
        )
        repository.store_verdict(
            run_id=run_id,
            claim_id=claim_id,
            verdict=verdict,
            policy_version=POLICY_VERSION,
            evidence_persistence_ids=evidence_ids,
            policy_inputs={
                "extraction_confidence": claim.extraction_confidence,
                "claim_low_quality": claim.low_quality,
                "evidence_low_quality": best_evidence_is_low_quality,
                "numeric_slot_results": [result.overall.value for result in numeric_results],
                "numeric_slot_indices": [result.slot_index for result in numeric_results],
                "nli_results": [
                    {
                        "evidence_id": str(evidence_id),
                        **asdict(result),
                        "label": result.label.value,
                    }
                    for evidence_id, result in zip(evidence_ids, classifications)
                ],
                "policy_nli_evidence_ids": [
                    str(evidence_id)
                    for evidence_id, score in zip(evidence_ids, reranker_scores)
                    if thresholds.tau_ret is not None and score >= thresholds.tau_ret
                ],
                "best_reranker_score": best_reranker_score,
                "thresholds": asdict(thresholds),
                "part_outcomes": [],
                "retrieval_empty": not evidence,
                "retrieval": [
                    {
                        "evidence_id": str(evidence_id),
                        "rank": rank,
                        "retrieval_rank": item.rank,
                        "retrieval_score": item.score,
                        "bm25_score": item.bm25_score,
                        "bm25_rank": item.bm25_rank,
                        "dense_score": item.dense_score,
                        "dense_rank": item.dense_rank,
                        "rrf_score": item.rrf_score,
                        "reranker_score": score,
                    }
                    for rank, (evidence_id, item, score) in enumerate(
                        zip(evidence_ids, ranked, reranker_scores), start=1
                    )
                ],
            },
        )
        results.append(ClaimVerdictResult(claim_id, verdict, evidence))
    return results


def _score_unpersisted_pairs(
    repository: PersistenceRepository,
    run_id: UUID,
    claim_id: UUID,
    claim: Claim,
    evidence: list[EvidenceChunk],
    evidence_ids: list[UUID],
    reranker: EvidenceReranker | None,
) -> list[float]:
    """Reuse exact prior pair scores and run the model only for new retrieved evidence."""
    existing = repository.list_reranker_results(run_id, claim_id)
    score_by_evidence = dict(existing)
    missing_indexes = [
        index
        for index, evidence_id in enumerate(evidence_ids)
        if evidence_id not in score_by_evidence
    ]
    if missing_indexes:
        scorer = reranker or get_reranker_service()
        missing_evidence = [evidence[index] for index in missing_indexes]
        scores = scorer.score_pairs(claim, missing_evidence)
        if len(scores) != len(missing_indexes):
            raise ValueError("reranker must return one score for every retrieved item")
        new_results = [
            (evidence_ids[index], score)
            for index, score in zip(missing_indexes, scores)
        ]
        repository.store_reranker_results(
            run_id=run_id,
            claim_id=claim_id,
            results=new_results,
            model_id=RERANKER_MODEL_ID,
            model_revision=RERANKER_MODEL_REVISION,
        )
        score_by_evidence.update(new_results)
    return [score_by_evidence[evidence_id] for evidence_id in evidence_ids]


def _classify_unpersisted_pairs(
    repository: PersistenceRepository,
    run_id: UUID,
    claim_id: UUID,
    claim: Claim,
    evidence: list[EvidenceChunk],
    evidence_ids: list[UUID],
    nli_service: NLIService | None,
) -> list[NLIClassification]:
    """Reuse exact prior pair outputs and infer only evidence pairs not yet persisted."""
    existing = repository.list_nli_results(run_id, claim_id)
    existing_by_evidence = {
        item.evidence_chunk_id: item.classification
        for item in existing
    }
    missing_indexes = [
        index
        for index, evidence_id in enumerate(evidence_ids)
        if evidence_id not in existing_by_evidence
    ]
    missing_evidence = [evidence[index] for index in missing_indexes]
    inferred = classify_claim_evidence(claim, missing_evidence, service=nli_service)
    classifications = [
        existing_by_evidence.get(evidence_id)
        for evidence_id in evidence_ids
    ]
    for index, classification in zip(missing_indexes, inferred):
        classifications[index] = classification
    if any(result is None for result in classifications):
        raise RuntimeError("NLI output is missing a retrieved evidence pair")
    return [result for result in classifications if result is not None]


def _claim_persistence_id(claim: Claim) -> UUID:
    """Rebuild the approved document-scoped claim primary key."""
    return derive_uuid(
        claim.document_id,
        claim.source_anchor_id,
        claim.char_start,
        claim.char_end,
    )


def _evidence_persistence_id(evidence: EvidenceChunk) -> UUID:
    """Rebuild the document-scoped evidence primary key without replacing B's chunk ID."""
    return derive_uuid(evidence.document_id, "evidence_chunk", evidence.chunk_id)
