"""Initialize the handoff workflow tables on a new database."""

from persistence.session import get_engine
from persistence.workflow import Base


def main() -> None:
    """Create missing workflow tables."""
    Base.metadata.create_all(get_engine())


if __name__ == "__main__":
    main()
