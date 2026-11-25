"""Database records for projects, queued runs, immutable traces, and review events."""

from sqlalchemy import JSON, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

json_type = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    """Metadata shared by the workflow records."""


class Project(Base):
    """A collection of uploaded documents."""
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    data: Mapped[dict] = mapped_column(json_type)


class Document(Base):
    """An uploaded PDF and its optional companion CSV."""
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("project_id", "pdf_hash"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    pdf_hash: Mapped[str] = mapped_column(String(64))
    pdf_path: Mapped[str]
    csv_path: Mapped[str | None]
    data: Mapped[dict] = mapped_column(json_type)


class CompanionFile(Base):
    """A separately stored CSV attached to one PDF document."""
    __tablename__ = "companion_files"
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), primary_key=True)
    storage_path: Mapped[str]
    file_hash: Mapped[str] = mapped_column(String(64))


class Run(Base):
    """A durable analysis job and its metadata."""
    __tablename__ = "analysis_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), index=True)
    queued_at: Mapped[str]
    data: Mapped[dict] = mapped_column(json_type)


class Claim(Base):
    """Stable identity across reanalysis jobs."""
    __tablename__ = "claims"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)


class Trace(Base):
    """A claim's immutable system output in one run."""
    __tablename__ = "claim_traces"
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id"), primary_key=True)
    data: Mapped[dict] = mapped_column(json_type)


class Review(Base):
    """An append-only review of a particular run's verdict."""
    __tablename__ = "review_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id"))
    created_at: Mapped[str]
    data: Mapped[dict] = mapped_column(json_type)


class GraphEdge(Base):
    """Claim to review provenance."""
    __tablename__ = "graph_edges"
    to_id: Mapped[str] = mapped_column(ForeignKey("review_events.id"), primary_key=True)
    from_id: Mapped[str] = mapped_column(ForeignKey("claims.id"))
    run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id"))
    edge_type: Mapped[str]


class Annotation(Base):
    """Human ground truth associated with a stable claim ID."""
    __tablename__ = "annotations"
    id: Mapped[str] = mapped_column(primary_key=True)
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), index=True)
    data: Mapped[dict] = mapped_column(json_type)

