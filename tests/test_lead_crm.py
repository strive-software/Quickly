"""Lead CRM data stays shared while unpublished copy stays out of the queue."""

from fastapi import BackgroundTasks
from fastapi import HTTPException
import pytest
from sqlalchemy import select

from app.models import (CustomEmailOverride, PersonalizedEmailDraft, UnsubscribeAudit,
                        UnconfirmedUnsubscribeRequest, LeadReply)
from app.app_settings import (put_setting, EMAIL_VERIFICATION_ENABLED,
                              EMAIL_VERIFICATION_API_KEY)
from app.routers.campaigns import (save_custom_email_draft, release_custom_email_draft,
                                   bulk_add_leads_to_campaign, import_campaign_leads,
                                   trigger_verification_for_campaign, write_custom_email,
                                   patch_campaign_lead)
from app.routers.leads import (create_lead, get_lead_emails, get_lead_research,
                               put_lead_research, retry_lead_verification,
                               review_unconfirmed_unsubscribe,
                               _fetch_lead_interactions, _reset_all_enrollments_for_lead,
                               _mutate_lead_recover)
from app.schemas import (CampaignLeadAdd, CustomEmailDraftWrite, CustomEmailWrite, DraftReleaseRequest,
                         LeadResearchWrite, LeadResearchSource, LeadCreateWithCampaign)
from app.schemas import UnconfirmedUnsubscribeReview
from app.schemas import CampaignLeadEnrollmentPatch
from tests.conftest import (make_campaign, make_campaign_lead, make_lead, make_sequence,
                            make_inbox, make_queue_slot, make_email_log)


async def test_research_shared_across_campaigns(session):
    lead = await make_lead(session)
    a = await make_campaign(session, name="A")
    b = await make_campaign(session, name="B")
    await make_campaign_lead(session, a.id, lead.id)
    await make_campaign_lead(session, b.id, lead.id)
    await put_lead_research(lead.id, LeadResearchWrite(
        summary="LinkedIn: finance lead", sources=[LeadResearchSource(url="https://example.com", title="Profile")],
        expected_updated_at=None), session)
    research = await get_lead_research(lead.id, session)
    assert research["summary"] == "LinkedIn: finance lead"
    assert research["sources"][0]["url"] == "https://example.com"
    assert research["updated_at"].endswith("Z")
    with pytest.raises(HTTPException) as conflict:
        await put_lead_research(lead.id, LeadResearchWrite(
            summary="stale", sources=[], expected_updated_at=None), session)
    assert conflict.value.status_code == 409


async def test_draft_does_not_release_personalized_step(session):
    campaign = await make_campaign(session, paused=True)
    sequence = await make_sequence(session, campaign.id, sequence_type="personalized")
    lead = await make_lead(session)
    enrollment = await make_campaign_lead(session, campaign.id, lead.id)
    enrollment.enrollment_status = "needs_custom_email"
    await session.flush()
    saved = await save_custom_email_draft(campaign.id, lead.id, sequence.id,
                                  CustomEmailDraftWrite(subject="Hi {{name}}", body="Draft for {{name}}",
                                                        is_html=False, expected_updated_at=None), session)
    assert await session.scalar(select(CustomEmailOverride).where(CustomEmailOverride.campaign_lead_id == enrollment.id)) is None
    emails = await get_lead_emails(lead.id, None, session)
    pending = emails["items"][0]
    assert pending["status"] == "paused"  # campaign pause is visible independently of draft
    assert pending["draft"]["body"] == "Draft for {{name}}"
    assert pending["draft"]["updated_at"].endswith("Z")
    assert pending["body"] != "Draft for Test Lead"
    with pytest.raises(HTTPException) as stale_release:
        await release_custom_email_draft(campaign.id, lead.id, sequence.id,
                                         DraftReleaseRequest(expected_updated_at="2020-01-01T00:00:00Z"),
                                         BackgroundTasks(), session)
    assert stale_release.value.status_code == 409
    await release_custom_email_draft(campaign.id, lead.id, sequence.id,
                                     DraftReleaseRequest(expected_updated_at=saved["draft"]["updated_at"]),
                                     BackgroundTasks(), session)
    override = await session.scalar(select(CustomEmailOverride).where(CustomEmailOverride.campaign_lead_id == enrollment.id))
    assert override.body == "Draft for {{name}}"
    assert await session.scalar(select(PersonalizedEmailDraft).where(PersonalizedEmailDraft.campaign_lead_id == enrollment.id)) is None


async def test_draft_preserves_already_released_content(session):
    campaign = await make_campaign(session)
    sequence = await make_sequence(session, campaign.id, sequence_type="personalized")
    lead = await make_lead(session)
    enrollment = await make_campaign_lead(session, campaign.id, lead.id)
    inbox = await make_inbox(session)
    slot = await make_queue_slot(session, enrollment.id, inbox.id)
    session.add(CustomEmailOverride(campaign_lead_id=enrollment.id, sequence_id=sequence.id,
                                    subject="Live", body="Existing sendable copy", is_html=False))
    await session.flush()
    await save_custom_email_draft(campaign.id, lead.id, sequence.id,
                                  CustomEmailDraftWrite(subject="New", body="Unreleased edit",
                                                        is_html=False, expected_updated_at=None), session)
    item = (await get_lead_emails(lead.id, None, session))["items"][0]
    assert item["body"] == "Existing sendable copy"
    assert item["draft"]["body"] == "Unreleased edit"
    assert item["override"]["body"] == "Existing sendable copy"
    assert item["slot_id"] == slot.id
    with pytest.raises(HTTPException) as conflict:
        await save_custom_email_draft(campaign.id, lead.id, sequence.id,
            CustomEmailDraftWrite(subject="Lost", body="stale", expected_updated_at=None), session)
    assert conflict.value.status_code == 409


async def test_draft_release_rejects_sent_and_wrong_campaign_steps(session):
    campaign = await make_campaign(session)
    another = await make_campaign(session, name="Another")
    sequence = await make_sequence(session, campaign.id, sequence_type="personalized")
    lead = await make_lead(session)
    await make_campaign_lead(session, campaign.id, lead.id)
    with pytest.raises(HTTPException) as wrong:
        await save_custom_email_draft(another.id, lead.id, sequence.id,
            CustomEmailDraftWrite(body="No", expected_updated_at=None), session)
    assert wrong.value.status_code == 404
    await make_email_log(session, lead.id, campaign.id, sequence_index=sequence.position)
    with pytest.raises(HTTPException) as sent:
        await save_custom_email_draft(campaign.id, lead.id, sequence.id,
            CustomEmailDraftWrite(body="Too late", expected_updated_at=None), session)
    assert sent.value.status_code == 409


async def test_thread_reply_editor_uses_raw_tokens_and_never_saves_placeholder(session):
    campaign = await make_campaign(session)
    sequence = await make_sequence(session, campaign.id, sequence_type="personalized",
                                   subject="", body="Hi {{name}}")
    lead = await make_lead(session, name="Ada")
    await make_campaign_lead(session, campaign.id, lead.id)
    item = (await get_lead_emails(lead.id, None, session))["items"][0]
    assert item["subject"] == "(reply in thread)"
    assert item["editing_source"]["subject"] == ""
    assert item["editing_source"]["body"] == "Hi {{name}}"
    await save_custom_email_draft(campaign.id, lead.id, sequence.id,
        CustomEmailDraftWrite(subject="(reply in thread)", body="Hi {{name}}",
                              expected_updated_at=None), session)
    item = (await get_lead_emails(lead.id, None, session))["items"][0]
    assert item["editing_source"]["subject"] is None
    assert item["editing_source"]["body"] == "Hi {{name}}"


async def test_legacy_immediate_write_invalidates_older_draft(session):
    campaign = await make_campaign(session)
    sequence = await make_sequence(session, campaign.id, sequence_type="personalized")
    lead = await make_lead(session)
    enrollment = await make_campaign_lead(session, campaign.id, lead.id)
    await save_custom_email_draft(campaign.id, lead.id, sequence.id,
        CustomEmailDraftWrite(subject="Old", body="Old draft", expected_updated_at=None), session)
    await write_custom_email(campaign.id, lead.id, sequence.id,
        CustomEmailWrite(subject="Live", body="Live content"), BackgroundTasks(), session)
    assert await session.scalar(select(PersonalizedEmailDraft).where(
        PersonalizedEmailDraft.campaign_lead_id == enrollment.id)) is None
    live = await session.scalar(select(CustomEmailOverride).where(
        CustomEmailOverride.campaign_lead_id == enrollment.id))
    assert live.body == "Live content"


async def test_unsubscribe_audit_in_lead_timeline(session):
    campaign = await make_campaign(session)
    lead = await make_lead(session)
    await make_campaign_lead(session, campaign.id, lead.id)
    session.add(UnsubscribeAudit(lead_id=lead.id, campaign_id=campaign.id,
                                 request_method="POST", mechanism="rfc8058_one_click",
                                 ip_address="192.0.2.1", user_agent="test"))
    await session.flush()
    events = await _fetch_lead_interactions(session, lead.id)
    audit = next(event for event in events if event["kind"] == "unsubscribed")
    assert audit["mechanism"] == "rfc8058_one_click"
    assert audit["request_method"] == "POST"


async def test_unconfirmed_request_review_accepts_only_explicit_action(session, monkeypatch):
    async def no_webhooks(*_args, **_kwargs):
        return None
    monkeypatch.setattr("app.tracking_events.emit_unsubscribe_webhooks", no_webhooks)
    campaign = await make_campaign(session)
    lead = await make_lead(session)
    enrollment = await make_campaign_lead(session, campaign.id, lead.id)
    enrollment.sending_paused = True
    request = UnconfirmedUnsubscribeRequest(lead_id=lead.id, campaign_id=campaign.id,
        paused_by_request=True, request_count=2)
    session.add(request)
    await session.flush()
    timeline = await _fetch_lead_interactions(session, lead.id)
    pending = next(event for event in timeline if event["kind"] == "unconfirmed_unsubscribe")
    assert pending["request_id"] == request.id
    assert pending["review_decision"] is None
    response = await review_unconfirmed_unsubscribe(lead.id, request.id,
        UnconfirmedUnsubscribeReview(decision="accepted"), session)
    assert response["decision"] == "accepted"
    assert enrollment.enrollment_status == "unsubscribed"
    audit = await session.scalar(select(UnsubscribeAudit).where(UnsubscribeAudit.lead_id == lead.id))
    assert audit.mechanism == "operator_confirmation"
    with pytest.raises(HTTPException) as duplicate:
        await review_unconfirmed_unsubscribe(lead.id, request.id,
            UnconfirmedUnsubscribeReview(decision="rejected"), session)
    assert duplicate.value.status_code == 409


async def test_reject_unconfirmed_request_keeps_enrollment_paused(session):
    campaign = await make_campaign(session)
    lead = await make_lead(session)
    enrollment = await make_campaign_lead(session, campaign.id, lead.id)
    enrollment.sending_paused = True
    request = UnconfirmedUnsubscribeRequest(lead_id=lead.id, campaign_id=campaign.id,
        paused_by_request=True)
    session.add(request)
    await session.flush()
    await review_unconfirmed_unsubscribe(lead.id, request.id,
        UnconfirmedUnsubscribeReview(decision="rejected"), session)
    assert enrollment.sending_paused is True
    assert enrollment.enrollment_status == "active"
    assert await session.scalar(select(UnsubscribeAudit).where(UnsubscribeAudit.lead_id == lead.id)) is None


async def test_scheduled_preview_uses_slot_and_sent_history_survives_removed_enrollment(session):
    campaign = await make_campaign(session)
    sequence = await make_sequence(session, campaign.id, subject="Hello {{name}}", body="Hi {{name}}")
    lead = await make_lead(session, name="Ada")
    enrollment = await make_campaign_lead(session, campaign.id, lead.id)
    inbox = await make_inbox(session, email="sender@example.com")
    await make_queue_slot(session, enrollment.id, inbox.id)
    pending = (await get_lead_emails(lead.id, None, session))["items"][0]
    assert pending["status"] == "scheduled"
    assert pending["subject"] == "Hello Ada"
    assert pending["body"] == "Hi Ada"
    assert pending["from_email"] == "sender@example.com"
    await make_email_log(session, lead.id, campaign.id, sequence_index=sequence.position,
                         inbox_id=inbox.id, subject="Delivered")
    await session.delete(enrollment)
    await session.flush()
    history = (await get_lead_emails(lead.id, None, session))["items"]
    assert len(history) == 1
    assert history[0]["status"] == "sent"
    assert history[0]["subject"] == "Delivered"


async def test_existing_slot_reports_delivery_holds_without_losing_schedule(session):
    campaign = await make_campaign(session)
    await make_sequence(session, campaign.id)
    lead = await make_lead(session)
    enrollment = await make_campaign_lead(session, campaign.id, lead.id)
    inbox = await make_inbox(session)
    await make_queue_slot(session, enrollment.id, inbox.id)

    async def status():
        return (await get_lead_emails(lead.id, None, session))["items"][0]

    assert (await status())["status"] == "scheduled"
    campaign.paused = True
    assert (await status())["status"] == "paused"
    campaign.paused = False
    enrollment.sending_paused = True
    assert (await status())["status"] == "paused"
    enrollment.sending_paused = False
    lead.email_verification_status = "pending"
    assert (await status())["status_reason"] == "email_verification"
    lead.email_verification_status = "valid"
    lead.status = "unsubscribed"
    assert (await status())["status_reason"] == "lead_status"
    lead.status = "active"
    session.add(LeadReply(lead_id=lead.id, campaign_id=campaign.id))
    await session.flush()
    item = await status()
    assert item["status"] == "blocked"
    assert item["status_reason"] == "replied"
    assert item["scheduled_at"] is not None


async def test_new_lead_is_pending_but_cached_verified_lead_keeps_verdict(session, monkeypatch):
    calls = []

    async def fake_verify(ids, **_kwargs):
        calls.extend(ids)

    async def fake_detect(_pairs):
        return None

    monkeypatch.setattr("app.routers.campaigns._run_background_verification", fake_verify)
    monkeypatch.setattr("app.routers.campaigns._detect_providers_background", fake_detect)
    campaign = await make_campaign(session)
    campaign.match_lead_provider = False
    await make_sequence(session, campaign.id)
    inbox = await make_inbox(session)
    await session.flush()
    from tests.conftest import make_campaign_inbox
    await make_campaign_inbox(session, campaign.id, inbox.id)
    cached = await make_lead(session, email="cached@example.com")
    cached.email_verification_status = "valid"
    await session.flush()
    bg = BackgroundTasks()
    result = await bulk_add_leads_to_campaign(campaign.id, [
        CampaignLeadAdd(email="new@example.com", email_verification_status="valid"),
        CampaignLeadAdd(email=cached.email),
    ], skip_duplicates=False, background_tasks=bg, db=session)
    assert result["verification_queued"] is True
    assert result["verification_pending"] == 1
    new = await session.scalar(select(type(cached)).where(type(cached).email == "new@example.com"))
    assert new.email_verification_status == "pending"
    assert cached.email_verification_status == "valid"
    assert result["results"][0]["slots_created"] == 0
    assert len(bg.tasks) == 1


async def test_single_create_enrolls_and_queues_verification(session, monkeypatch):
    async def fake_detect(_pairs):
        return None
    monkeypatch.setattr("app.routers.campaigns._detect_providers_background", fake_detect)
    campaign = await make_campaign(session)
    campaign.match_lead_provider = False
    bg = BackgroundTasks()
    lead = await create_lead(LeadCreateWithCampaign(campaign_id=campaign.id,
        email="solo@example.com", name="Solo"), bg, session)
    assert lead.email == "solo@example.com"
    assert lead.email_verification_status == "pending"
    assert lead.campaigns[0].campaign_id == campaign.id
    assert len(bg.tasks) == 1


async def test_single_create_preserves_existing_profile_and_verification(session, monkeypatch):
    async def fake_detect(_pairs):
        return None
    monkeypatch.setattr("app.routers.campaigns._detect_providers_background", fake_detect)
    campaign = await make_campaign(session)
    campaign.match_lead_provider = False
    existing = await make_lead(session, email="existing@example.com")
    existing.company = "Acme"
    existing.job_title = "Director"
    existing.notes = "Keep these notes"
    existing.email_verification_status = None
    await session.commit()
    bg = BackgroundTasks()
    saved = await create_lead(LeadCreateWithCampaign(campaign_id=campaign.id,
        email=existing.email), bg, session)
    assert saved.company == "Acme"
    assert saved.job_title == "Director"
    assert saved.notes == "Keep these notes"
    assert saved.email_verification_status is None
    assert len(bg.tasks) == 0


async def test_csv_import_automatically_queues_verification(session, monkeypatch):
    async def fake_detect(_pairs):
        return None
    monkeypatch.setattr("app.routers.campaigns._detect_providers_background", fake_detect)
    from tests.test_pause_inbox_and_bulk_duplicates import _make_csv_upload
    campaign = await make_campaign(session)
    campaign.match_lead_provider = False
    bg = BackgroundTasks()
    result = await import_campaign_leads(campaign.id,
        _make_csv_upload("email,name,email_verification_status\ncsv@example.com,CSV,valid\n"),
        background_tasks=bg, db=session)
    assert result["verification_queued"] is True
    assert result["verification_pending"] == 1
    assert result["added"] == 1
    assert result["total_rows"] == 1
    assert len(bg.tasks) == 1


async def test_explicit_verification_marks_failed_and_unverified_pending_before_dispatch(session):
    await put_setting(session, EMAIL_VERIFICATION_ENABLED, "true")
    await put_setting(session, EMAIL_VERIFICATION_API_KEY, "test-key")
    campaign = await make_campaign(session)
    lead = await make_lead(session)
    await make_campaign_lead(session, campaign.id, lead.id)
    bg = BackgroundTasks()
    response = await trigger_verification_for_campaign(campaign.id, bg, reverify=False, db=session)
    assert response["queued"] == 1
    assert lead.email_verification_status == "pending"
    assert len(bg.tasks) == 1
    lead.email_verification_status = "verification_error"
    lead.email_verification_result = {"error": "Email verification is not enabled"}
    await session.commit()
    retry_bg = BackgroundTasks()
    response = await retry_lead_verification(lead.id, retry_bg, session)
    assert response["verification_status"] == "pending"
    assert lead.email_verification_result is None
    assert len(retry_bg.tasks) == 1
    lead.email_verification_status = "valid"
    await session.commit()
    with pytest.raises(HTTPException) as cached:
        await retry_lead_verification(lead.id, BackgroundTasks(), session)
    assert cached.value.status_code == 409


async def test_http_create_research_retry_and_email_routes(session, monkeypatch):
    await put_setting(session, EMAIL_VERIFICATION_ENABLED, "true")
    await put_setting(session, EMAIL_VERIFICATION_API_KEY, "test-key")
    import httpx
    from app.main import app
    from app.database import get_db
    from app.auth import get_current_user

    async def fake_verify(_ids, **_kwargs):
        return None
    async def fake_detect(_pairs):
        return None
    async def test_db():
        yield session

    monkeypatch.setattr("app.routers.campaigns._run_background_verification", fake_verify)
    monkeypatch.setattr("app.routers.campaigns._detect_providers_background", fake_detect)
    campaign = await make_campaign(session)
    campaign.match_lead_provider = False
    await make_sequence(session, campaign.id, sequence_type="personalized")
    app.dependency_overrides[get_db] = test_db
    app.dependency_overrides[get_current_user] = lambda: object()
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            created = await client.post("/api/leads", json={"campaign_id": campaign.id,
                "email": "http@example.com", "name": "HTTP"})
            assert created.status_code == 200, created.text
            lead_id = created.json()["id"]
            assert created.json()["email_verification_status"] == "pending"
            research = await client.put(f"/api/leads/{lead_id}/research", json={
                "summary": "Source notes", "sources": [], "expected_updated_at": None})
            assert research.status_code == 200, research.text
            assert research.json()["updated_at"].endswith("Z")
            stale = await client.put(f"/api/leads/{lead_id}/research", json={
                "summary": "stale", "sources": [], "expected_updated_at": None})
            assert stale.status_code == 409
            emails = await client.get(f"/api/leads/{lead_id}/emails")
            assert emails.status_code == 200
            assert emails.json()["items"][0]["status"] == "blocked"
            retry = await client.post(f"/api/leads/{lead_id}/verify")
            assert retry.status_code == 200
            assert retry.json()["verification_status"] == "pending"
            campaign_retry = await client.post(f"/api/campaigns/{campaign.id}/leads/verify")
            assert campaign_retry.status_code == 200, campaign_retry.text
            assert campaign_retry.json()["queued"] == 1
    finally:
        app.dependency_overrides.clear()


async def test_unsubscribe_review_hold_blocks_resume_and_recovery(session):
    campaign = await make_campaign(session)
    lead = await make_lead(session)
    enrollment = await make_campaign_lead(session, campaign.id, lead.id)
    enrollment.sending_paused = True
    enrollment.unsubscribe_review_hold = True
    request = UnconfirmedUnsubscribeRequest(lead_id=lead.id, campaign_id=campaign.id,
                                            paused_by_request=True)
    session.add(request)
    await session.commit()

    with pytest.raises(HTTPException) as open_error:
        await patch_campaign_lead(campaign.id, lead.id,
            CampaignLeadEnrollmentPatch(sending_paused=False), BackgroundTasks(), session)
    assert open_error.value.status_code == 409
    await _mutate_lead_recover(lead, "corrected@example.com", False)
    await _reset_all_enrollments_for_lead(session, lead.id)
    assert enrollment.sending_paused is True
    assert enrollment.unsubscribe_review_hold is True

    from datetime import datetime, timezone
    request.review_decision = "rejected"
    request.reviewed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await session.commit()
    result = await patch_campaign_lead(campaign.id, lead.id,
        CampaignLeadEnrollmentPatch(sending_paused=False), BackgroundTasks(), session)
    assert result["unsubscribe_review_hold"] is False
    assert enrollment.sending_paused is False


async def test_recovery_preserves_confirmed_unsubscribe(session):
    campaign = await make_campaign(session)
    lead = await make_lead(session)
    enrollment = await make_campaign_lead(session, campaign.id, lead.id)
    lead.status = "unsubscribed"
    enrollment.enrollment_status = "unsubscribed"
    enrollment.sending_paused = True
    await session.flush()
    await _mutate_lead_recover(lead, "corrected@example.com", False)
    await _reset_all_enrollments_for_lead(session, lead.id)
    assert lead.status == "unsubscribed"
    assert enrollment.enrollment_status == "unsubscribed"
    assert enrollment.sending_paused is True


async def test_explicit_verification_requires_config_before_mutation(session):
    campaign = await make_campaign(session)
    lead = await make_lead(session)
    await make_campaign_lead(session, campaign.id, lead.id)
    lead.email_verification_status = "verification_error"
    lead.email_verification_result = {"error": "Previous failure"}
    await session.commit()
    with pytest.raises(HTTPException) as disabled:
        await retry_lead_verification(lead.id, BackgroundTasks(), session)
    assert disabled.value.status_code == 503
    assert lead.email_verification_status == "verification_error"
    assert lead.email_verification_result == {"error": "Previous failure"}

    await put_setting(session, EMAIL_VERIFICATION_ENABLED, "true")
    await session.commit()
    with pytest.raises(HTTPException) as missing_key:
        await trigger_verification_for_campaign(campaign.id, BackgroundTasks(), reverify=False, db=session)
    assert missing_key.value.status_code == 503
    assert lead.email_verification_status == "verification_error"
    assert lead.email_verification_result == {"error": "Previous failure"}
