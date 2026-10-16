"""UTC revision tokens for lead research and unpublished email drafts."""

from datetime import datetime, timezone

from fastapi import HTTPException


def revision(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def require_revision(actual: datetime | None, expected: str | None) -> None:
    if expected is None:
        if actual is not None:
            raise HTTPException(409, "Record changed; reload before saving")
        return
    try:
        parsed = datetime.fromisoformat(expected.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("Timezone required")
        expected_utc = revision(parsed)
    except ValueError:
        raise HTTPException(400, "expected_updated_at must be an ISO UTC timestamp") from None
    if revision(actual) != expected_utc:
        raise HTTPException(409, "Record changed; reload before saving")
