"""A-owned retrieval adapter over persisted evidence for downstream verification."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from domain.schemas import Claim, EvidenceChunk
from eg_common.settings import Settings, get_settings
from persistence.mappers import evidence_chunk_from_row, source_anchor_from_row
from persistence.models import DocumentRow, EvidenceChunkRow, ProjectRow, SourceLocationRow
from persistence.repositories import PersistenceNotFoundError, PersistenceRepository
from worker.orchestration.embeddings import (
    EMBEDDING_DIMENSION,
    EMBEDDING_MODEL_ID,
    EMBEDDING_MODEL_REVISION,
    EmbeddingService,
    get_embedding_service,
)

_TOKEN_PATTERN = re.compile(r"\w+", flags=re.UNICODE)


class RetrievalContractError(ValueError):
    """An invalid ranking or duplicate source identity was supplied."""


@dataclass(frozen=True)
class RankedEvidence:
    """A ranked evidence chunk with its score and original provenance intact."""

    chunk: EvidenceChunk
    score: float
    rank: int
    bm25_score: float | None = None
    dense_score: float | None = None
    rrf_score: float | None = None
    bm25_rank: int | None = None
    dense_rank: int | None = None


def _tokens(text: str) -> list[str]:
    """Tokenize text into normalized Unicode word terms."""
    return [token.casefold() for token in _TOKEN_PATTERN.findall(text)]


def bm25_retrieve(
    query: str,
    chunks: Iterable[EvidenceChunk],
    *,
    top_k: int,
    k1: float,
    b: float,
) -> list[RankedEvidence]:
    """Rank evidence chunks with BM25 and return positive matches in stable order."""
    if top_k < 1:
        raise ValueError("top_k must be at least 1")
    if not math.isfinite(k1) or k1 <= 0:
        raise ValueError("k1 must be finite and greater than zero")
    if not math.isfinite(b) or not 0 <= b <= 1:
        raise ValueError("b must be between zero and one")

    query_terms = _tokens(query)
    if not query_terms:
        return []

    documents = list(chunks)
    if not documents:
        return []

    tokenized = [_tokens(chunk.text) for chunk in documents]
    lengths = [len(terms) for terms in tokenized]
    average_length = sum(lengths) / len(lengths)
    if average_length == 0:
        return []

    document_frequency: Counter[str] = Counter()
    frequencies = [Counter(terms) for terms in tokenized]
    for terms in tokenized:
        document_frequency.update(set(terms))

    scored: list[tuple[int, EvidenceChunk, float]] = []
    for index, chunk in enumerate(documents):
        score = 0.0
        for term in query_terms:
            term_frequency = frequencies[index][term]
            if term_frequency == 0:
                continue
            frequency = document_frequency[term]
            inverse_document_frequency = math.log(
                1.0 + (len(documents) - frequency + 0.5) / (frequency + 0.5)
            )
            normalization = k1 * (
                1.0 - b + b * lengths[index] / average_length
            )
            score += inverse_document_frequency * (
                term_frequency * (k1 + 1.0) / (term_frequency + normalization)
            )
        if score > 0:
            scored.append((index, chunk, score))

    scored.sort(key=lambda item: (-item[2], item[0]))
    return [
        RankedEvidence(chunk=chunk, score=score, rank=rank, bm25_score=score, bm25_rank=rank)
        for rank, (_index, chunk, score) in enumerate(scored[:top_k], start=1)
    ]


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[RankedEvidence]],
    *,
    rrf_k: int,
    top_k: int,
) -> list[RankedEvidence]:
    """Fuse ranked lists by reciprocal rank, deduplicating document-scoped chunks."""
    if rrf_k < 1:
        raise ValueError("rrf_k must be at least 1")
    if top_k < 1:
        raise ValueError("top_k must be at least 1")

    chunks: dict[tuple[UUID, UUID], EvidenceChunk] = {}
    fused_scores: dict[tuple[UUID, UUID], float] = {}
    components: dict[tuple[UUID, UUID], dict[str, float | int | None]] = {}
    for ranking in rankings:
        seen_in_ranking: set[tuple[UUID, UUID]] = set()
        for item in ranking:
            if item.rank < 1:
                raise RetrievalContractError("ranking positions must be positive")
            key = (item.chunk.document_id, item.chunk.chunk_id)
            existing = chunks.get(key)
            if existing is not None and existing != item.chunk:
                raise RetrievalContractError(
                    "duplicate evidence identity has conflicting content or provenance"
                )
            chunks[key] = item.chunk
            component = components.setdefault(
                key,
                {"bm25_score": None, "dense_score": None, "bm25_rank": None, "dense_rank": None},
            )
            for score_name, rank_name in (
                ("bm25_score", "bm25_rank"), ("dense_score", "dense_rank")
            ):
                score = getattr(item, score_name)
                if score is not None:
                    component[score_name] = score
                    component[rank_name] = item.rank
            if key in seen_in_ranking:
                continue
            seen_in_ranking.add(key)
            fused_scores[key] = fused_scores.get(key, 0.0) + 1.0 / (rrf_k + item.rank)

    ordered = sorted(
        fused_scores,
        key=lambda key: (
            -fused_scores[key],
            str(key[0]),
            str(key[1]),
        ),
    )[:top_k]
    return [
        RankedEvidence(
            chunk=chunks[key], score=fused_scores[key], rank=rank,
            rrf_score=fused_scores[key], **components[key],
        )
        for rank, key in enumerate(ordered, start=1)
    ]


def retrieve_project_evidence(
    session: Session,
    project_id: UUID,
    query: str,
    *,
    exclude_source: tuple[UUID, str] | None = None,
    settings: Settings | None = None,
    embedding_service: EmbeddingService | None = None,
) -> list[RankedEvidence]:
    """Retrieve persisted evidence with BM25 and pgvector, then fuse both rankings."""
    if session.get(ProjectRow, project_id) is None:
        raise PersistenceNotFoundError(f"project {project_id} does not exist")

    repository = PersistenceRepository(session)
    document_ids = session.scalars(
        select(DocumentRow.id)
        .where(DocumentRow.project_id == project_id, DocumentRow.status == "complete")
        .order_by(DocumentRow.id)
    )
    persisted_chunks: list[EvidenceChunk] = []
    for document_id in document_ids:
        ingestion_result = repository.get_ingestion_result(document_id)
        persisted_chunks.extend(ingestion_result.chunks)

    if exclude_source is not None:
        excluded_document_id, excluded_anchor_id = exclude_source
        persisted_chunks = [
            chunk
            for chunk in persisted_chunks
            if (chunk.document_id, chunk.anchor.anchor_id)
            != (excluded_document_id, excluded_anchor_id)
        ]

    config = settings or get_settings()
    bm25_results = bm25_retrieve(
        query,
        persisted_chunks,
        top_k=config.retrieval_top_k,
        k1=config.retrieval_bm25_k1,
        b=config.retrieval_bm25_b,
    )
    dense_results = dense_retrieve_project_evidence(
        session,
        project_id,
        query,
        exclude_source=exclude_source,
        settings=config,
        embedding_service=embedding_service,
    )
    return reciprocal_rank_fusion(
        [bm25_results, dense_results],
        rrf_k=config.retrieval_rrf_k,
        top_k=config.retrieval_top_k,
    )


def dense_retrieve_project_evidence(
    session: Session,
    project_id: UUID,
    query: str,
    *,
    exclude_source: tuple[UUID, str] | None = None,
    settings: Settings | None = None,
    embedding_service: EmbeddingService | None = None,
) -> list[RankedEvidence]:
    """Rank matching-model project evidence with pgvector cosine distance."""
    config = settings or get_settings()
    if session.get_bind().dialect.name != "postgresql":
        return []

    has_embeddings = session.scalar(
        select(EvidenceChunkRow.id)
        .join(DocumentRow, DocumentRow.id == EvidenceChunkRow.document_id)
        .where(
            DocumentRow.project_id == project_id,
            DocumentRow.status == "complete",
            EvidenceChunkRow.embedding.is_not(None),
            EvidenceChunkRow.embedding_model_id == EMBEDDING_MODEL_ID,
            EvidenceChunkRow.embedding_model_revision == EMBEDDING_MODEL_REVISION,
        )
        .limit(1)
    )
    if has_embeddings is None:
        return []

    service = embedding_service or get_embedding_service()
    query_vectors = service.embed_texts([query])
    if len(query_vectors) != 1 or len(query_vectors[0]) != EMBEDDING_DIMENSION:
        raise RetrievalContractError("query embedding must contain 384 dimensions")
    query_vector = query_vectors[0]
    if any(not math.isfinite(value) for value in query_vector):
        raise RetrievalContractError("query embedding must contain finite values")

    distance = EvidenceChunkRow.embedding.cosine_distance(query_vector).label("cosine_distance")
    statement = (
        select(EvidenceChunkRow, SourceLocationRow, distance)
        .join(
            SourceLocationRow,
            (SourceLocationRow.id == EvidenceChunkRow.source_location_id)
            & (SourceLocationRow.document_id == EvidenceChunkRow.document_id),
        )
        .join(DocumentRow, DocumentRow.id == EvidenceChunkRow.document_id)
        .where(
            DocumentRow.project_id == project_id,
            DocumentRow.status == "complete",
            EvidenceChunkRow.embedding.is_not(None),
            EvidenceChunkRow.embedding_model_id == EMBEDDING_MODEL_ID,
            EvidenceChunkRow.embedding_model_revision == EMBEDDING_MODEL_REVISION,
        )
    )
    if exclude_source is not None:
        excluded_document_id, excluded_anchor_id = exclude_source
        statement = statement.where(
            ~(
                (EvidenceChunkRow.document_id == excluded_document_id)
                & (SourceLocationRow.anchor_id == excluded_anchor_id)
            )
        )
    rows = session.execute(
        statement.order_by(
            distance,
            EvidenceChunkRow.document_id,
            EvidenceChunkRow.ordinal,
        ).limit(config.retrieval_top_k)
    )
    return [
        RankedEvidence(
            chunk=evidence_chunk_from_row(row, source_anchor_from_row(location)),
            score=1.0 - float(cosine_distance),
            rank=rank,
            dense_score=1.0 - float(cosine_distance),
            dense_rank=rank,
        )
        for rank, (row, location, cosine_distance) in enumerate(rows, start=1)
    ]


def retrieve_for_claim(
    session: Session,
    project_id: UUID,
    claim: Claim,
    *,
    settings: Settings | None = None,
    embedding_service: EmbeddingService | None = None,
) -> list[RankedEvidence]:
    """Retrieve evidence for a claim while excluding its own source anchor."""
    return retrieve_project_evidence(
        session,
        project_id,
        claim.claim_text,
        exclude_source=(claim.document_id, claim.source_anchor_id),
        settings=settings,
        embedding_service=embedding_service,
    )
