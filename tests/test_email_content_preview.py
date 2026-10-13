"""Queued previews resolve live content; sent previews preserve submitted content."""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app import jobs
from app.models import CustomEmailOverride, EmailLog, SequenceVariant
from app.routers.schedule import scheduled_detail, sent_detail
from app.sender import SendResult
from tests.conftest import (
    make_campaign, make_campaign_inbox, make_campaign_lead, make_email_log,
    make_lead, make_queue_slot, make_sequence,
)
from tests.test_send_auth_failure import _SessionCtx, _make_smtp_inbox


@pytest.mark.parametrize("job", ["batch", "slot"])
@pytest.mark.parametrize("is_html", [True, False])
async def test_success_captures_submitted_content(session, monkeypatch, job, is_html):
    inbox = await _make_smtp_inbox(session)
    campaign = await make_campaign(session, sending_days=list(range(7)),
        sending_hours_start="00:00", sending_hours_end="23:59")
    campaign.track_opens = campaign.track_clicks = is_html
    sequence = await make_sequence(session, campaign.id, subject="Hi {{name}}",
        body='<p>Original {{name}} <a href="https://example.com">link</a></p>' if is_html else "Original {{name}}")
    sequence.is_html = is_html
    lead = await make_lead(session, name="Alex")
    cl = await make_campaign_lead(session, campaign.id, lead.id)
    await make_campaign_inbox(session, campaign.id, inbox.id)
    slot = await make_queue_slot(session, cl.id, inbox.id,
        scheduled_date=datetime.utcnow() - timedelta(minutes=1))
    submitted = []
    def send(**kwargs):
        submitted.append(kwargs)
        return SendResult(message_id="<captured@example.com>")
    monkeypatch.setattr(jobs, "send_email", send)
    monkeypatch.setattr(jobs, "AsyncSessionLocal", lambda: _SessionCtx(session))
    await (jobs.run_send_job() if job == "batch" else jobs.send_slot_job(slot.id))
    log = (await session.execute(select(EmailLog))).scalar_one()
    assert log.body == submitted[0]["body"]
    assert log.is_html == submitted[0]["is_html"] == is_html
    assert "Original Alex" in log.body
    if is_html:
        assert "https://example.com" not in log.body  # tracking was already injected
    sequence.body = "Changed template"
    sequence.is_html = not is_html
    lead.name = "Changed name"
    await session.flush()
    detail = await sent_detail(log.id, session)
    assert detail["subject"] == "Hi Alex"
    assert detail["sequence_body"] == submitted[0]["body"]
    assert detail["sequence_is_html"] == is_html
    assert detail["body_available"] is True


async def test_historical_body_is_unavailable_not_reconstructed(session):
    campaign = await make_campaign(session)
    await make_sequence(session, campaign.id, body="This is not the original")
    lead = await make_lead(session)
    log = await make_email_log(session, lead.id, campaign.id)
    detail = await sent_detail(log.id, session)
    assert detail["body_available"] is False
    assert detail["sequence_body"] == ""


@pytest.mark.parametrize("personalized", [True, False])
async def test_queue_resolves_personalization_and_assigned_variant(session, personalized):
    inbox = await _make_smtp_inbox(session)
    campaign = await make_campaign(session)
    campaign.send_all_as_text = True
    seq = await make_sequence(session, campaign.id,
        sequence_type="personalized" if personalized else "standard", body="default")
    lead = await make_lead(session, name="Alex")
    cl = await make_campaign_lead(session, campaign.id, lead.id)
    slot = await make_queue_slot(session, cl.id, inbox.id)
    if personalized:
        session.add(CustomEmailOverride(campaign_lead_id=cl.id, sequence_id=seq.id,
            subject="For {{name}}", body="Saved {{name}}", is_html=True))
    else:
        variant = SequenceVariant(sequence_id=seq.id, subject="For {{name}}",
            body="Saved {{name}}", is_html=True, enabled=True)
        session.add(variant)
        await session.flush()
        slot.variant_id = variant.id
    await session.flush()
    detail = await scheduled_detail(slot.id, session)
    assert detail["subject"] == "For Alex"
    assert detail["sequence_body"] == "Saved Alex"
    assert detail["sequence_is_html"] is False  # campaign format overrides sequence
