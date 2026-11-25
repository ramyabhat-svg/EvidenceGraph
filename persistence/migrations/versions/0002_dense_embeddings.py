"""Add pinned-model pgvector embeddings to persisted evidence chunks."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "0002_dense_embeddings"
down_revision: Union[str, None] = "0001_persistence_foundation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Enable pgvector and add nullable embedding values for safe backfill."""
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.add_column("evidence_chunks", sa.Column("embedding", Vector(384), nullable=True))
    op.add_column("evidence_chunks", sa.Column("embedding_model_id", sa.String(128)))
    op.add_column("evidence_chunks", sa.Column("embedding_model_revision", sa.String(64)))
    if bind.dialect.name == "postgresql":
        op.create_check_constraint(
            "ck_evidence_chunks_embedding_metadata",
            "evidence_chunks",
            "(embedding IS NULL AND embedding_model_id IS NULL "
            "AND embedding_model_revision IS NULL) OR "
            "(embedding IS NOT NULL AND embedding_model_id IS NOT NULL "
            "AND embedding_model_revision IS NOT NULL)",
        )
        op.create_index(
            "ix_evidence_chunks_embedding_hnsw",
            "evidence_chunks",
            ["embedding"],
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
            postgresql_where=sa.text("embedding IS NOT NULL"),
        )


def downgrade() -> None:
    """Remove the index and embedding columns without dropping shared extensions."""
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.drop_index("ix_evidence_chunks_embedding_hnsw", table_name="evidence_chunks")
        op.drop_constraint(
            "ck_evidence_chunks_embedding_metadata", "evidence_chunks", type_="check"
        )
    op.drop_column("evidence_chunks", "embedding_model_revision")
    op.drop_column("evidence_chunks", "embedding_model_id")
    op.drop_column("evidence_chunks", "embedding")
