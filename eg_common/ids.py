"""Platform identifier helpers."""

from uuid import NAMESPACE_URL, UUID, uuid5


def derive_uuid(*parts: object) -> UUID:
    """Derive a stable platform UUID distinct from Member B's identifier namespace."""
    value = "evidencegraph-platform|" + "|".join(str(part) for part in parts)
    return uuid5(NAMESPACE_URL, value)
