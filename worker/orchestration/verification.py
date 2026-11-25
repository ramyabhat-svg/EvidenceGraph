"""Retrieve project evidence and persist B's numeric verification results."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from domain.schemas import Claim, EvidenceChunk
from eg_common.ids import derive_uuid
from eg_common.settings import Settings, get_settings
from persistence.models import DocumentRow, EvidenceChunkRow
from persistence.repositories import (
    PersistenceContractError,
    PersistenceNotFoundError,
    PersistenceRepository,
)
from worker.extraction.evidence_slots import slots_from_chunk
from worker.orchestration.decision_policy import POLICY_VERSION
from worker.orchestration.embeddings import (
    EMBEDDING_MODEL_ID,
    EMBEDDING_MODEL_REVISION,
    EmbeddingService,
)
from worker.orchestration.nli import NLI_MODEL_ID, NLI_MODEL_REVISION
from worker.orchestration.reranking import RERANKER_MODEL_ID, RERANKER_MODEL_REVISION
from worker.orchestration.retrieval import RankedEvidence, retrieve_for_claim
from worker.orchestration.run_identity import analysis_run_id
from worker.verification.numeric import (
    VALIDATOR_VERSION,
    NumericConfig,
    SlotVerification,
    verify_numeric_claim,
)


@dataclass(frozen=True)
class ClaimNumericVerification:
    """Numeric verification outputs and the evidence retrieved for one persisted claim."""

    claim_id: UUID
    results: list[SlotVerification]
    evidence: list[EvidenceChunk]
    ranked_evidence: list[RankedEvidence]


def verify_and_persist_document_claims(
    session: Session,
    document_id: UUID,
    *,
    settings: Settings | None = None,
    embedding_service: EmbeddingService | None = None,
) -> list[ClaimNumericVerification]:
    """Retrieve evidence for each persisted claim, verify numerics, and persist idempotently."""
    document = session.get(DocumentRow, document_id)
    if document is None:
        raise PersistenceNotFoundError(f"document {document_id} does not exist")
    repository = PersistenceRepository(session)
    claims = repository.list_claims(document_id)
    if not claims:
        return []

    config = settings or get_settings()
    numeric_config = NumericConfig()
    run_id = analysis_run_id(document_id, config)
    run_configuration = {
        "retrieval_top_k": config.retrieval_top_k,
        "retrieval_bm25_k1": config.retrieval_bm25_k1,
        "retrieval_bm25_b": config.retrieval_bm25_b,
        "retrieval_rrf_k": config.retrieval_rrf_k,
        "reranker_batch_size": config.reranker_batch_size,
        "numeric_approx_multiplier": str(numeric_config.approx_multiplier),
        "policy_tau_ext": config.policy_tau_ext,
        "policy_tau_ret": config.policy_tau_ret,
        "policy_tau_e": config.policy_tau_e,
        "policy_tau_c": config.policy_tau_c,
    }
    repository.create_analysis_run(
        run_id=run_id,
        document_id=document_id,
        configuration=run_configuration,
        model_versions={
            "numeric": VALIDATOR_VERSION,
            "embedding": f"{EMBEDDING_MODEL_ID}@{EMBEDDING_MODEL_REVISION}",
            "nli": f"{NLI_MODEL_ID}@{NLI_MODEL_REVISION}",
            "reranker": f"{RERANKER_MODEL_ID}@{RERANKER_MODEL_REVISION}",
        },
        policy_version=POLICY_VERSION,
    )

    output = []
    for claim in claims:
        ranked = retrieve_for_claim(
            session,
            document.project_id,
            claim,
            settings=config,
            embedding_service=embedding_service,
        )
        evidence = [item.chunk for item in ranked]
        results = verify_numeric_claim(claim, evidence, numeric_config)
        persisted_claim_id = _persisted_claim_id(claim)
        evidence_ids = _evidence_persistence_ids(session, ranked)
        repository.store_numeric_verifications(
            run_id=run_id,
            claim_id=persisted_claim_id,
            results=results,
            evidence_persistence_ids=evidence_ids,
        )
        output.append(
            ClaimNumericVerification(
                claim_id=persisted_claim_id,
                results=results,
                evidence=evidence,
                ranked_evidence=ranked,
            )
        )
    return output


def _persisted_claim_id(claim: Claim) -> UUID:
    """Return the platform claim key while retaining B's extractor claim ID in storage."""
    return derive_uuid(
        claim.document_id,
        claim.source_anchor_id,
        claim.char_start,
        claim.char_end,
    )


def _evidence_persistence_ids(
    session: Session,
    ranked: list[RankedEvidence],
) -> list[UUID]:
    """Map B's ordered checks to document-scoped chunks, including repeated source IDs."""
    evidence_ids: list[UUID] = []
    for item in ranked:
        evidence_id = derive_uuid(
            item.chunk.document_id,
            "evidence_chunk",
            item.chunk.chunk_id,
        )
        row = session.get(EvidenceChunkRow, evidence_id)
        if (
            row is None
            or row.document_id != item.chunk.document_id
            or row.source_chunk_id != item.chunk.chunk_id
        ):
            raise PersistenceContractError(
                "retrieved evidence is missing its persisted source chunk"
            )
        evidence_ids.extend([evidence_id] * len(slots_from_chunk(item.chunk)))
    return evidence_ids
