"""Enforce the existing one-companion-CSV-per-PDF document contract."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_one_companion_csv"
down_revision: Union[str, None] = "0004_reranker_results"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Ensure concurrent CSV uploads cannot create multiple companions."""
    op.create_index(
        "uq_documents_parent_csv",
        "documents",
        ["parent_document_id"],
        unique=True,
        sqlite_where=sa.text("file_type = 'csv'"),
        postgresql_where=sa.text("file_type = 'csv'"),
    )


def downgrade() -> None:
    """Remove the companion uniqueness constraint."""
    op.drop_index("uq_documents_parent_csv", table_name="documents")
