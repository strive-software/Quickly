"""Manual sequence barriers are enforced in reservations and sender preflight."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, delete
from app.models import ManualStepRecord, QueueSlot
from app.queue_logic import reserve_slots_for_lead, email_step_allowed, refresh_manual_enrollment
from tests.conftest import (make_campaign, make_inbox, make_lead, make_campaign_lead,
                      make_sequence, make_email_log)


async def setup_steps(session):
    campaign = await make_campaign(session, sending_days=list(range(7)),
                                   sending_hours_start="00:00", sending_hours_end="23:59")
    inbox = await make_inbox(session)
    lead = await make_lead(session)
    cl = await make_campaign_lead(session, campaign.id, lead.id)
    first = await make_sequence(session, campaign.id, position=0)
    manual = await make_sequence(session, campaign.id, position=1, sequence_type="linkedin")
    last = await make_sequence(session, campaign.id, position=2, wait_days_after_previous=2)
    return campaign, inbox, lead, cl, [first, manual, last]


async def reserve(session, data, last_sent=-1):
    campaign, inbox, lead, cl, steps = data
    await reserve_slots_for_lead(session, cl.id, campaign, [(inbox.id, inbox, 5)], steps,
                                 lead.id, last_sent_sequence_index=last_sent)
    await session.flush()
    return (await session.execute(select(QueueSlot).order_by(QueueSlot.sequence_index))).scalars().all()


@pytest.mark.asyncio
async def test_hold_ignore_done_and_pending(session):
    data = await setup_steps(session)
    campaign, inbox, lead, cl, steps = data
    assert [s.sequence_index for s in await reserve(session, data)] == [0]
    assert not await email_step_allowed(session, cl, steps[1])
    assert not await email_step_allowed(session, cl, steps[2])
    await session.execute(delete(QueueSlot))
    steps[1].manual_mode = "ignore"
    assert [s.sequence_index for s in await reserve(session, data)] == [0, 2]
    assert await email_step_allowed(session, cl, steps[2])
    await session.execute(delete(QueueSlot))
    steps[1].manual_mode = "hold"
    completed = datetime.now(timezone.utc) + timedelta(days=3)
    record = ManualStepRecord(campaign_lead_id=cl.id, sequence_id=steps[1].id,
                              message="Hello", sent_at=completed)
    session.add(record)
    await make_email_log(session, lead.id, campaign.id, 0, inbox.id)
    slots = await reserve(session, data, last_sent=0)
    assert [s.sequence_index for s in slots] == [2]
    assert slots[0].scheduled_date.date() == (completed + timedelta(days=2)).date()
    assert await email_step_allowed(session, cl, steps[2])
    record.sent_at = None
    await session.flush()
    assert not await email_step_allowed(session, cl, steps[2])
    record.ignored = True
    await session.flush()
    assert await email_step_allowed(session, cl, steps[2])


@pytest.mark.asyncio
async def test_final_manual_step_keeps_enrollment_open(session):
    data = await setup_steps(session)
    campaign, inbox, lead, cl, steps = data
    await session.delete(steps[2])
    await make_email_log(session, lead.id, campaign.id, 0, inbox.id)
    await refresh_manual_enrollment(session, cl)
    assert cl.enrollment_status == "contacted"
    record = ManualStepRecord(campaign_lead_id=cl.id, sequence_id=steps[1].id,
                              sent_at=datetime.now(timezone.utc), message="done")
    session.add(record)
    await session.flush()
    await refresh_manual_enrollment(session, cl)
    assert cl.enrollment_status == "completed"
    record.sent_at = None
    await session.flush()
    await refresh_manual_enrollment(session, cl)
    assert cl.enrollment_status == "completed"
    record.ignored = True
    await session.flush()
    await refresh_manual_enrollment(session, cl)
    assert cl.enrollment_status == "completed"
    cl.enrollment_status = "replied"
    record.ignored = False
    await session.flush()
    await refresh_manual_enrollment(session, cl)
    assert cl.enrollment_status == "replied"


@pytest.mark.asyncio
async def test_filtered_sequences_keep_actual_positions(session):
    data = await setup_steps(session)
    campaign, inbox, lead, cl, steps = data
    # ASAP can omit an unwritten personalized step. Queue joins use original position.
    data = campaign, inbox, lead, cl, [steps[2]]
    assert [s.sequence_index for s in await reserve(session, data)] == [2]


@pytest.mark.asyncio
async def test_reopening_hold_after_later_send_does_not_resend(session):
    from app.queue_logic import recalculate_queue_after_sequence_change_for_leads
    from tests.conftest import make_campaign_inbox
    campaign, inbox, lead, cl, steps = await setup_steps(session)
    await make_campaign_inbox(session, campaign.id, inbox.id)
    await make_sequence(session, campaign.id, position=3)
    await make_email_log(session, lead.id, campaign.id, 0, inbox.id)
    await make_email_log(session, lead.id, campaign.id, 2, inbox.id)
    record = ManualStepRecord(campaign_lead_id=cl.id, sequence_id=steps[1].id,
                             message="draft", sent_at=None)
    session.add(record)
    await session.flush()
    await refresh_manual_enrollment(session, cl)
    await recalculate_queue_after_sequence_change_for_leads(session, [cl.id])
    assert list((await session.scalars(select(QueueSlot))).all()) == []
    record.sent_at = datetime.now(timezone.utc)
    await session.flush()
    await recalculate_queue_after_sequence_change_for_leads(session, [cl.id])
    assert [s.sequence_index for s in (await session.scalars(select(QueueSlot))).all()] == [3]


@pytest.mark.asyncio
@pytest.mark.parametrize("ignore_mode", [True, False])
@pytest.mark.parametrize("done", [True, False])
async def test_ignored_step_never_changes_email_timing(session, ignore_mode, done):
    data = await setup_steps(session)
    campaign, inbox, lead, cl, steps = data
    steps[1].manual_mode = "ignore" if ignore_mode else "hold"
    steps[1].wait_days_after_previous = 100
    session.add(ManualStepRecord(campaign_lead_id=cl.id, sequence_id=steps[1].id,
        message="draft", ignored=not ignore_mode,
        sent_at=datetime.now(timezone.utc) + timedelta(days=100) if done else None))
    await session.flush()
    slots = await reserve(session, data)
    assert [s.sequence_index for s in slots] == [0, 2]
    assert slots[1].scheduled_date.date() == slots[0].scheduled_date.date() + timedelta(days=2)


@pytest.mark.asyncio
async def test_final_ignored_step_completes_and_stays_terminal(session):
    campaign, inbox, lead, cl, steps = await setup_steps(session)
    await session.delete(steps[2])
    steps[1].manual_mode = "ignore"
    await make_email_log(session, lead.id, campaign.id, 0, inbox.id)
    await refresh_manual_enrollment(session, cl)
    assert cl.enrollment_status == "completed"
    steps[1].manual_mode = "hold"
    await session.flush()
    await refresh_manual_enrollment(session, cl)
    assert cl.enrollment_status == "completed"


@pytest.mark.asyncio
async def test_manual_step_cannot_send_test_email(session, monkeypatch):
    from unittest.mock import Mock
    from fastapi import HTTPException
    from app.routers.campaigns import send_test_email, TestEmailRequest
    campaign, inbox, lead, cl, steps = await setup_steps(session)
    sender = Mock(side_effect=AssertionError("Manual step must never call sender"))
    monkeypatch.setattr("app.sender.send_email", sender)
    with pytest.raises(HTTPException) as error:
        await send_test_email(campaign.id, TestEmailRequest(
            sequence_id=steps[1].id, to_email="test@example.com"), session)
    assert error.value.status_code == 400
    sender.assert_not_called()


@pytest.mark.asyncio
async def test_batch_sender_skips_slot_deleted_after_batch_fetch(session, monkeypatch):
    from unittest.mock import Mock
    from tests.test_send_auth_failure import _SessionCtx, _make_smtp_inbox, _make_due_slot
    from app.jobs import run_send_job
    inbox = await _make_smtp_inbox(session)
    slot = await _make_due_slot(session, inbox)
    original_execute = session.execute
    invalidated = False

    async def invalidate_during_credentials(statement, *args, **kwargs):
        nonlocal invalidated
        # Credential lookup runs after the due batch was fetched.
        if not invalidated and "FROM smtp_account" in str(statement):
            invalidated = True
            await original_execute(delete(QueueSlot).where(QueueSlot.id == slot.id))
            await session.commit()
        return await original_execute(statement, *args, **kwargs)

    monkeypatch.setattr(session, "execute", invalidate_during_credentials)
    monkeypatch.setattr("app.jobs.AsyncSessionLocal", lambda: _SessionCtx(session))
    sender = Mock(side_effect=AssertionError("Invalidated slot must never send"))
    monkeypatch.setattr("app.jobs.send_email", sender)
    await run_send_job()
    assert invalidated
    sender.assert_not_called()


@pytest.mark.asyncio
async def test_manual_edit_never_resumes_explicitly_completed_enrollment(session):
    campaign, inbox, lead, cl, steps = await setup_steps(session)
    await make_email_log(session, lead.id, campaign.id, 0, inbox.id)
    cl.enrollment_status = "completed"
    await refresh_manual_enrollment(session, cl)
    assert cl.enrollment_status == "completed"


@pytest.mark.asyncio
async def test_asap_completion_honors_progress_past_omitted_email(session):
    campaign, inbox, lead, cl, steps = await setup_steps(session)
    campaign.custom_sequence_mode = "asap"
    steps[1].sequence_type = "personalized"
    await make_email_log(session, lead.id, campaign.id, 0, inbox.id)
    await make_email_log(session, lead.id, campaign.id, 2, inbox.id)
    await refresh_manual_enrollment(session, cl)
    assert cl.enrollment_status == "completed"


@pytest.mark.asyncio
@pytest.mark.parametrize("skip", ["campaign_ignore", "lead_ignore", "asap"])
async def test_first_email_after_skipped_step_does_not_drift(session, monkeypatch, skip):
    import app.queue_logic as queue_logic
    campaign, inbox, lead, cl, steps = await setup_steps(session)
    await session.delete(steps[2])
    steps[0].sequence_type = "linkedin" if skip != "asap" else "personalized"
    steps[0].manual_mode = "ignore" if skip == "campaign_ignore" else "hold"
    steps[1].sequence_type = "standard"
    steps[1].wait_days_after_previous = 3
    if skip == "lead_ignore":
        session.add(ManualStepRecord(campaign_lead_id=cl.id, sequence_id=steps[0].id,
                                    ignored=True, message=""))
    await session.flush()
    selected = [steps[1]] if skip == "asap" else steps[:2]
    data = campaign, inbox, lead, cl, selected
    today = datetime(2030, 1, 7, 10)
    for offset in (0, 1):
        now = today + timedelta(days=offset)
        monkeypatch.setattr(queue_logic, "_campaign_now", lambda _: now)
        await session.execute(delete(QueueSlot))
        slots = await reserve(session, data)
        assert [s.sequence_index for s in slots] == [1]
        assert slots[0].scheduled_date.date() == now.date()
