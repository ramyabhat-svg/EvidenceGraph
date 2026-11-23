"""Platform UUID namespace tests."""

from eg_common.ids import derive_uuid
from worker.ingestion.anchors import stable_uuid


def test_derived_uuid_is_stable_and_distinct_from_member_b_namespace() -> None:
    """Platform IDs are stable but never collide with B's namespace for equal parts."""
    parts = ("document", "anchor", 4, 10)

    assert derive_uuid(*parts) == derive_uuid(*parts)
    assert derive_uuid(*parts) != stable_uuid(*parts)
