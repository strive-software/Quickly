"""Worker behavior for durable, automatically queued email verification."""
import asyncio

import pytest
from sqlalchemy import select

from app.app_settings import (
    EMAIL_VERIFICATION_API_KEY,
    EMAIL_VERIFICATION_ENABLED,
    EMAIL_VERIFICATION_PROVIDER,
    put_setting,
)
from app.email_verification import VerificationResult
from app.models import Lead
from app.routers import campaigns
from tests.conftest import make_lead


async def _pending_lead(session, email: str):
    lead = await make_lead(session, email=email)
    lead.email_verification_status = "pending"
    await session.commit()
    return lead


async def _configure(session, *, api_key: str | None = "test-key"):
    await put_setting(session, EMAIL_VERIFICATION_ENABLED, "true")
    await put_setting(session, EMAIL_VERIFICATION_PROVIDER, "mailtester_ninja")
    if api_key is not None:
        await put_setting(session, EMAIL_VERIFICATION_API_KEY, api_key)
    await session.commit()


@pytest.mark.asyncio
async def test_pending_lead_becomes_error_when_provider_key_missing(session, monkeypatch):
    lead = await _pending_lead(session, "missing-key@example.com")
    await _configure(session, api_key=None)

    async def forbid_network(*args, **kwargs):
        raise AssertionError("Missing config must not call the provider")
    monkeypatch.setattr("app.email_verification.verify_single", forbid_network)
    await campaigns._run_background_verification([lead.id])

    await session.refresh(lead)
    assert lead.email_verification_status == "verification_error"
    assert lead.email_verification_result == {
        "error": "Email verification API key is not configured"
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("last_status, expected", [(200, "valid"), (429, "verification_error")])
async def test_429_retries_through_actual_worker(session, monkeypatch, last_status, expected):
    lead = await _pending_lead(session, "retry@example.com")
    await _configure(session)
    monkeypatch.setattr(campaigns, "_verification_last_check_at", None)
    statuses = [429, 429, last_status]
    sleeps = []
    original_sleep = asyncio.sleep

    async def fast_sleep(seconds):
        sleeps.append(seconds)
        await original_sleep(0)

    class FakeResponse:
        def __init__(self, status):
            self.status_code = status
        def json(self):
            return {"code": "ok", "message": "Accepted"}

    class FakeClient:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return None
        async def get(self, url, timeout):
            assert "retry%40example.com" in url or "retry@example.com" in url
            return FakeResponse(statuses.pop(0))

    monkeypatch.setattr("app.email_verification.httpx.AsyncClient", FakeClient)
    monkeypatch.setattr(asyncio, "sleep", fast_sleep)
    await campaigns._run_background_verification([lead.id])

    await session.refresh(lead)
    assert lead.email_verification_status == expected
    assert statuses == []
    assert sleeps == ([3, 6] if last_status == 200 else [3, 6, 9])
    if expected == "verification_error":
        assert lead.email_verification_result == {
            "error": "Email verification provider could not complete the check"
        }


@pytest.mark.asyncio
async def test_overlapping_jobs_check_each_pending_id_once_with_pacing(session, monkeypatch):
    first = await _pending_lead(session, "first@example.com")
    second = await _pending_lead(session, "second@example.com")
    await _configure(session)
    monkeypatch.setattr(campaigns, "_verification_last_check_at", None)
    calls = []
    first_started = asyncio.Event()
    release_first = asyncio.Event()

    async def fake_provider(email, api_key, provider_name):
        calls.append((email, asyncio.get_running_loop().time()))
        if email == first.email:
            first_started.set()
            await release_first.wait()
        return VerificationResult(email, "valid", raw={"code": "ok"})

    monkeypatch.setattr("app.email_verification.verify_single", fake_provider)
    first_job = asyncio.create_task(campaigns._run_background_verification([first.id, second.id]))
    await asyncio.wait_for(first_started.wait(), timeout=2)
    duplicate_job = asyncio.create_task(campaigns._run_background_verification([first.id, second.id]))
    await asyncio.sleep(0)
    assert len(calls) == 1  # second job cannot enter provider while first holds lock
    release_first.set()
    await asyncio.gather(first_job, duplicate_job)

    assert [email for email, _ in calls] == [first.email, second.email]
    assert calls[1][1] - calls[0][1] >= 0.95
    await session.refresh(first)
    await session.refresh(second)
    assert first.email_verification_status == second.email_verification_status == "valid"
