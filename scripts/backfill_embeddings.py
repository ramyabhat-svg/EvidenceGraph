"""Backfill vectors for existing completed evidence chunks."""

import logging

from eg_common.logging import configure_logging, log_event
from eg_common.settings import get_settings
from persistence.session import get_session_factory
from worker.orchestration.embeddings import backfill_missing_embeddings


def main() -> None:
    """Generate missing embeddings in configured batches and log the updated count."""
    settings = get_settings()
    configure_logging(settings.log_level)
    updated = backfill_missing_embeddings(
        get_session_factory(),
        settings=settings,
    )
    log_event(
        logging.getLogger("evidencegraph.embedding_backfill"),
        "embedding_backfill_finished",
        count=updated,
    )


if __name__ == "__main__":
    main()
