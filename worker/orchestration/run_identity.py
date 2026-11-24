"""Deterministic analysis-run identity shared by verification and verdict stages."""

from __future__ import annotations

from uuid import UUID

from eg_common.ids import derive_uuid
from eg_common.settings import Settings
from worker.orchestration.decision_policy import POLICY_VERSION
from worker.orchestration.embeddings import EMBEDDING_MODEL_ID, EMBEDDING_MODEL_REVISION
from worker.orchestration.nli import NLI_MODEL_ID, NLI_MODEL_REVISION
from worker.orchestration.reranking import RERANKER_MODEL_ID, RERANKER_MODEL_REVISION
from worker.verification.numeric import VALIDATOR_VERSION, NumericConfig


def analysis_run_id(document_id: UUID, settings: Settings) -> UUID:
    """Derive a stable ID from the document and effective run-level settings."""
    numeric_config = NumericConfig()
    return derive_uuid(
        document_id,
        "analysis-run",
        POLICY_VERSION,
        VALIDATOR_VERSION,
        EMBEDDING_MODEL_ID,
        EMBEDDING_MODEL_REVISION,
        NLI_MODEL_ID,
        NLI_MODEL_REVISION,
        RERANKER_MODEL_ID,
        RERANKER_MODEL_REVISION,
        settings.retrieval_top_k,
        settings.retrieval_bm25_k1,
        settings.retrieval_bm25_b,
        settings.retrieval_rrf_k,
        settings.reranker_batch_size,
        settings.policy_tau_ext,
        settings.policy_tau_ret,
        settings.policy_tau_e,
        settings.policy_tau_c,
        numeric_config.approx_multiplier,
    )
