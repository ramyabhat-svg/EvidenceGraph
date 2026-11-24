"""Pinned local CPU embedding service and idempotent evidence-vector persistence."""

from __future__ import annotations

import math
from functools import lru_cache
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from eg_common.settings import Settings, get_settings
from persistence.repositories import EvidenceEmbeddingInput, PersistenceRepository

EMBEDDING_MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_MODEL_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
EMBEDDING_DIMENSION = 384


class EmbeddingGenerationError(RuntimeError):
    """The local model failed to produce a valid configured embedding batch."""


class EmbeddingService(Protocol):
    """Interface for deterministic or production text embedding implementations."""

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Encode text strings into 384-dimensional vectors."""


class SentenceTransformerEmbeddingService:
    """Lazily load the approved pinned Sentence Transformer on CPU only."""

    def __init__(self, batch_size: int, model: Any | None = None) -> None:
        """Configure batched encoding and optionally accept a test model double."""
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        self._batch_size = batch_size
        self._model = model

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Encode a batch on CPU and reject vectors that violate the pinned model shape."""
        if not texts:
            return []
        model = self._model or self._load_model()
        try:
            encoded = model.encode(
                texts,
                batch_size=self._batch_size,
                show_progress_bar=False,
                convert_to_numpy=True,
                normalize_embeddings=True,
                device="cpu",
            )
        except Exception as exc:
            raise EmbeddingGenerationError("local embedding generation failed") from exc

        raw_vectors = encoded.tolist() if hasattr(encoded, "tolist") else encoded
        vectors = [[float(value) for value in vector] for vector in raw_vectors]
        if len(vectors) != len(texts) or any(
            len(vector) != EMBEDDING_DIMENSION
            or any(not math.isfinite(value) for value in vector)
            for vector in vectors
        ):
            raise EmbeddingGenerationError("local embedding output has an invalid shape")
        return vectors

    @staticmethod
    def _load_model() -> Any:
        """Load only the approved repository revision and explicitly select CPU."""
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise EmbeddingGenerationError(
                "sentence-transformers runtime dependency is unavailable"
            ) from exc
        try:
            return SentenceTransformer(
                EMBEDDING_MODEL_ID,
                revision=EMBEDDING_MODEL_REVISION,
                device="cpu",
            )
        except Exception as exc:
            raise EmbeddingGenerationError("approved local embedding model could not load") from exc


@lru_cache(maxsize=1)
def get_embedding_service() -> EmbeddingService:
    """Return the process-wide lazy embedding service configured from platform settings."""
    settings = get_settings()
    return SentenceTransformerEmbeddingService(settings.embedding_batch_size)


def generate_document_embeddings(
    session: Session,
    document_id: UUID,
    *,
    embedding_service: EmbeddingService | None = None,
    settings: Settings | None = None,
) -> int:
    """Generate and persist embeddings for every missing chunk in one document."""
    config = settings or get_settings()
    service = embedding_service or get_embedding_service()
    repository = PersistenceRepository(session)
    total_updated = 0
    while True:
        pending = repository.list_chunks_needing_embeddings(
            model_id=EMBEDDING_MODEL_ID,
            model_revision=EMBEDDING_MODEL_REVISION,
            limit=config.embedding_batch_size,
            document_id=document_id,
        )
        if not pending:
            return total_updated
        total_updated += _embed_and_store_batch(repository, pending, service)


def backfill_missing_embeddings(
    session_factory: sessionmaker[Session],
    *,
    embedding_service: EmbeddingService | None = None,
    settings: Settings | None = None,
) -> int:
    """Backfill missing or stale evidence vectors in safe, retryable database batches."""
    config = settings or get_settings()
    service = embedding_service or get_embedding_service()
    total_updated = 0
    while True:
        with session_factory() as session, session.begin():
            repository = PersistenceRepository(session)
            pending = repository.list_chunks_needing_embeddings(
                model_id=EMBEDDING_MODEL_ID,
                model_revision=EMBEDDING_MODEL_REVISION,
                limit=config.embedding_batch_size,
            )
            if not pending:
                return total_updated
            total_updated += _embed_and_store_batch(repository, pending, service)


def _embed_and_store_batch(
    repository: PersistenceRepository,
    pending: list[EvidenceEmbeddingInput],
    embedding_service: EmbeddingService,
) -> int:
    """Encode one persisted batch and store vectors grouped by their source document."""
    vectors = embedding_service.embed_texts([item.text for item in pending])
    if len(vectors) != len(pending):
        raise EmbeddingGenerationError("embedding service returned the wrong batch size")

    by_document: dict[UUID, dict[UUID, list[float]]] = {}
    for item, vector in zip(pending, vectors):
        by_document.setdefault(item.document_id, {})[item.source_chunk_id] = vector
    return sum(
        repository.store_evidence_embeddings(
            document_id=document_id,
            embeddings=embeddings,
            model_id=EMBEDDING_MODEL_ID,
            model_revision=EMBEDDING_MODEL_REVISION,
        )
        for document_id, embeddings in by_document.items()
    )
