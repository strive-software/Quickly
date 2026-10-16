"""Tests for Beacon ingest (signature + tracking_events integration)."""
from __future__ import annotations

import hashlib
import hmac
import json
from types import SimpleNamespace
from datetime import datetime

import pytest
from sqlalchemy import select

from fastapi import HTTPException
from app.models import EmailOpen, LeadUnsubscribeToken, UnsubscribeAudit, UnconfirmedUnsubscribeRequest, QueueSlot
from app.routers.beacon_ingest import _verify_signature, beacon_ingest
from app.tracking_events import record_email_open
from tests.conftest import make_inbox, make_campaign, make_lead, make_campaign_lead, make_email_log


async def _noop_webhook(*args, **kwargs):
    pass


def test_verify_signature_accepts_hmac_hex():
    body = b'{"inbox_id":1,"kind":"open"}'
    secret = "my-shared-secret-key-1234567890"
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    assert _verify_signature(body, secret, f"sha256={digest}")
    assert not _verify_signature(body, secret, "sha256=deadbeef")
    assert not _verify_signature(body, secret, "invalid")


@pytest.mark.asyncio
async def test_record_email_open_matches_beacon_payload(session, monkeypatch):
    monkeypatch.setattr("app.tracking_events.fire_webhook_event", _noop_webhook)

    inbox = await make_inbox(session)
    campaign = await make_campaign(session)
    lead = await make_lead(session)
    await make_campaign_lead(session, campaign.id, lead.id)
    email_log = await make_email_log(session, lead.id, campaign.id, inbox_id=inbox.id)
    token = email_log.open_token or str(email_log.id)
    await session.commit()

    recorded = await record_email_open(session, token, "9.9.9.9")
    assert recorded is True
    res = await session.execute(select(EmailOpen).where(EmailOpen.email_log_id == email_log.id))
    assert res.scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_beacon_unsubscribe_requires_signed_confirmed_post(session, monkeypatch):
    monkeypatch.setattr("app.tracking_events.fire_webhook_event", _noop_webhook)
    inbox = await make_inbox(session)
    inbox.beacon_webhook_secret = "test-secret"
    campaign = await make_campaign(session)
    lead = await make_lead(session)
    cl = await make_campaign_lead(session, campaign.id, lead.id)
    # A historical Beacon link remains valid after this inbox is removed
    # from the campaign's current sending configuration.
    session.add(LeadUnsubscribeToken(lead_id=lead.id, campaign_id=campaign.id, token="beacon-unsub"))
    session.add(QueueSlot(campaign_lead_id=cl.id, inbox_id=inbox.id, sequence_index=0,
                          scheduled_date=datetime(2030, 1, 1), position_in_day=1))
    await session.flush()

    async def post(payload, *, signed=True):
        body = json.dumps(payload).encode()
        digest = hmac.new(b"test-secret", body, hashlib.sha256).hexdigest()
        async def read_body():
            return body
        request = SimpleNamespace(body=read_body, headers={
            "X-Beacon-Signature": f"sha256={digest if signed else 'wrong'}"})
        return await beacon_ingest(request, db=session)

    base = {"inbox_id": inbox.id, "kind": "unsubscribe", "path_token": "beacon-unsub",
            "ip_address": "203.0.113.11", "user_agent": "Mail client"}
    with pytest.raises(HTTPException) as exc:
        await post(base, signed=False)
    assert exc.value.status_code == 401
    await session.refresh(cl)
    assert cl.sending_paused is False
    assert (await session.execute(select(UnconfirmedUnsubscribeRequest))).scalar_one_or_none() is None
    for payload in (base, {**base, "request_method": "GET", "unsubscribe_action": "browser_confirmation"},
                    {**base, "request_method": "POST", "unsubscribe_action": "unknown"}):
        assert (await post(payload))["pending_review"] is True
        await session.refresh(cl)
        assert cl.enrollment_status == "active"
        assert cl.sending_paused is True
        assert cl.unsubscribe_review_hold is True
    assert (await session.execute(select(UnsubscribeAudit))).scalar_one_or_none() is None
    pending = (await session.execute(select(UnconfirmedUnsubscribeRequest))).scalar_one()
    assert pending.request_count == 3
    assert pending.reviewed_at is None
    assert (await session.execute(select(QueueSlot.id))).scalar_one_or_none() is not None

    assert (await post({**base, "request_method": "POST",
                        "unsubscribe_action": "rfc8058_one_click"})) == {"ok": True}
    await session.refresh(cl)
    await session.refresh(pending)
    assert cl.enrollment_status == "unsubscribed"
    assert cl.unsubscribe_review_hold is False
    assert pending.review_decision == "confirmed"
    assert pending.reviewed_at is not None
    audit = (await session.execute(select(UnsubscribeAudit))).scalar_one()
    assert audit.mechanism == "beacon_one_click"
    assert audit.user_agent == "Mail client"
