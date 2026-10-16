"""Queued previews resolve live content; sent previews preserve submitted content."""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app import jobs
from app.models import CustomEmailOverride, EmailLog, SequenceVariant
from app.routers.schedule import scheduled_detail, sent_detail
from app.sender import SendResult
from app.settings_manager import settings
from app import time as time_provider
from tests.conftest import (
    make_campaign, make_campaign_inbox, make_campaign_lead, make_email_log,
    make_lead, make_queue_slot, make_sequence,
)
from tests.test_send_auth_failure import _SessionCtx, _make_smtp_inbox


def test_unsubscribe_base_requires_public_https_outside_test_mode(monkeypatch):
    monkeypatch.setattr(settings, "test_mode", False)
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    monkeypatch.delenv("QUICKLY_ALLOW_LOCAL_UNSUBSCRIBE_URL", raising=False)
    beacon = SimpleNamespace(beacon_connected=True)
    for base in ("http://example.com", "http://localhost:8000", "https://127.0.0.1",
                 "https://10.0.0.1", "https://internal.local", "https://user@example.com"):
        assert jobs._unsubscribe_base_for_inbox(beacon, "https://beacon.example", base) is None
    assert jobs._unsubscribe_base_for_inbox(beacon, "https://beacon.example",
                                            "https://quickly.example/") == "https://quickly.example"


@pytest.mark.parametrize("job", ["batch", "slot"])
@pytest.mark.parametrize("add_header,one_click", [(True, True), (True, False), (False, False)])
@pytest.mark.parametrize("is_html", [True, False])
@pytest.mark.parametrize("legacy_cname", [False, True])
async def test_mail_uses_reachable_unsubscribe_url(session, monkeypatch, job,
                                                    add_header, one_click, is_html, legacy_cname):
    inbox = await _make_smtp_inbox(session)
    inbox.beacon_connected = not legacy_cname
    inbox.beacon_base_url = "https://beacon.example"
    inbox.beacon_setup_token = "setup"
    if legacy_cname:
        inbox.tracking_domain = "track.example.com"
    campaign = await make_campaign(session, sending_days=list(range(7)),
        sending_hours_start="00:00", sending_hours_end="23:59")
    campaign.track_opens = campaign.track_clicks = is_html
    campaign.add_unsubscribe_header = add_header
    campaign.add_one_click_unsubscribe = one_click
    template = ('<p><a href="{{unsubscribe_link}}">Unsubscribe</a> {{unsubscribe_link}} '
                '<a href="https://example.com/page">More</a></p>') if is_html else \
               'Unsubscribe: {{unsubscribe_link}}'
    sequence = await make_sequence(session, campaign.id, body=template)
    sequence.is_html = is_html
    lead = await make_lead(session)
    cl = await make_campaign_lead(session, campaign.id, lead.id)
    await make_campaign_inbox(session, campaign.id, inbox.id)
    slot = await make_queue_slot(session, cl.id, inbox.id,
        scheduled_date=time_provider.now() - timedelta(seconds=1))
    captured = []
    async def register(*args, **kwargs):
        return None
    monkeypatch.setattr("app.beacon_client.register_beacon_mappings", register)
    monkeypatch.setattr(jobs, "send_email", lambda **kwargs:
        (captured.append(kwargs) or SendResult(message_id="<captured@example.com>")))
    monkeypatch.setattr(jobs, "AsyncSessionLocal", lambda: _SessionCtx(session))
    monkeypatch.setattr(settings, "base_url", "https://quickly.example/")
    await (jobs.run_send_job() if job == "batch" else jobs.send_slot_job(slot.id))

    assert len(captured) == 1
    sent = captured[0]
    unsub_origin = "https://track.example.com" if legacy_cname else "https://quickly.example"
    tracking_origin = "https://track.example.com" if legacy_cname else "https://beacon.example"
    assert sent["body"].count(f'{unsub_origin}/u/') == (2 if is_html else 1)
    if is_html:
        assert f'href="{unsub_origin}/u/' in sent["body"]
        assert f"{tracking_origin}/o/" in sent["body"]
        assert f"{tracking_origin}/c/" in sent["body"]
    if add_header:
        assert sent["list_unsubscribe_url"].startswith(f"{unsub_origin}/u/")
    else:
        assert sent["list_unsubscribe_url"] is None
    assert sent["list_unsubscribe_one_click"] is one_click


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
        scheduled_date=time_provider.now() - timedelta(seconds=1))
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
