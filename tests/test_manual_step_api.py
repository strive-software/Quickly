from datetime import datetime, timedelta, timezone
import pytest
from fastapi import BackgroundTasks, HTTPException
from pydantic import ValidationError
from app.models import LeadReply
from app.routers.manual_steps import list_manual_steps, update_manual_step
from app.routers.campaigns import create_sequence, update_sequence, duplicate_campaign, delete_sequence, list_campaign_leads
from app.schemas import ManualStepPatch, SequenceCreate, SequenceUpdate
from tests.conftest import make_campaign, make_sequence, make_lead, make_campaign_lead, make_email_log

pytestmark = pytest.mark.asyncio

async def setup(session):
    campaign = await make_campaign(session, sending_days=list(range(7)))
    lead = await make_lead(session)
    lead.priority = 'high'
    cl = await make_campaign_lead(session, campaign.id, lead.id)
    email = await make_sequence(session, campaign.id)
    manual = await make_sequence(session, campaign.id, position=1, sequence_type='linkedin', body='Hello')
    return campaign, lead, cl, email, manual

async def test_manual_history_is_campaign_scoped_and_ignore_is_independent(session):
    campaign, lead, cl, email, manual = await setup(session)
    other = await make_campaign(session)
    await make_campaign_lead(session, other.id, lead.id)
    other_step = await make_sequence(session, other.id, sequence_type='linkedin', body='Other draft')
    assert not (await list_manual_steps(campaign.id, db=session))[0].ready
    await make_email_log(session, lead.id, campaign.id)
    assert (await list_manual_steps(campaign.id, ready_only=True, priority='high', has_sent_email=True, db=session))[0].ready
    when = datetime.now(timezone.utc) - timedelta(days=1)
    result = await update_manual_step(campaign.id, lead.id, manual.id, ManualStepPatch(sent_at=when, ignored=True), BackgroundTasks(), session)
    assert result.sent and result.ignored and result.sent_at == when
    assert cl.enrollment_status == 'completed'
    assert (await list_campaign_leads(campaign.id,session))[0]['stage'] == 'Complete'
    unchanged = (await list_manual_steps(other.id, db=session))[0]
    assert unchanged.message == 'Other draft' and not unchanged.sent
    edited = await update_manual_step(campaign.id, lead.id, manual.id, ManualStepPatch(message='Edited'), BackgroundTasks(), session)
    assert edited.sent_at == when
    pending = await update_manual_step(campaign.id, lead.id, manual.id, ManualStepPatch(sent=False), BackgroundTasks(), session)
    assert not pending.sent and pending.ignored and cl.enrollment_status == 'completed'
    restored = await update_manual_step(campaign.id, lead.id, manual.id, ManualStepPatch(ignored=False), BackgroundTasks(), session)
    assert restored.ready and cl.enrollment_status == 'completed'
    assert (await list_campaign_leads(campaign.id,session))[0]['stage'] == 'Step 2 · LinkedIn'
    with pytest.raises(HTTPException) as error:
        await update_manual_step(other.id, lead.id, manual.id, ManualStepPatch(sent=True), BackgroundTasks(), session)
    assert error.value.status_code == 404

@pytest.mark.parametrize('payload', [{'sent':None},{'ignored':None},{'message':None},
    {'sent':False,'sent_at':'2026-01-01T00:00:00Z'}, {'sent':True,'message':''}])
async def test_invalid_manual_writes(session, payload):
    campaign,lead,cl,email,manual=await setup(session)
    with pytest.raises(HTTPException) as error:
        await update_manual_step(campaign.id,lead.id,manual.id,ManualStepPatch(**payload),BackgroundTasks(),session)
    assert error.value.status_code == 422

async def test_modes_readiness_and_duplicate_preserve_step_without_send_history(session):
    campaign, lead, cl, email, manual = await setup(session)
    await make_email_log(session,lead.id,campaign.id)
    await update_sequence(campaign.id,manual.id,SequenceUpdate(manual_mode='ignore'),BackgroundTasks(),session)
    assert cl.enrollment_status == 'completed'
    assert len(await list_manual_steps(campaign.id,ready_only=True,db=session)) == 1
    await update_sequence(campaign.id,manual.id,SequenceUpdate(manual_mode='hold'),BackgroundTasks(),session)
    assert cl.enrollment_status == 'completed'
    assert len(await list_manual_steps(campaign.id,ready_only=True,db=session)) == 1
    session.add(LeadReply(lead_id=lead.id,campaign_id=campaign.id));await session.flush()
    assert await list_manual_steps(campaign.id,ready_only=True,db=session) == []
    copy = await duplicate_campaign(campaign.id,session)
    from sqlalchemy import select
    from app.models import Sequence
    steps=list((await session.scalars(select(Sequence).where(Sequence.campaign_id==copy.id))).all())
    assert steps[1].sequence_type == 'linkedin' and steps[1].manual_mode == 'hold'
    assert await list_manual_steps(copy.id,db=session) == []
    with pytest.raises(HTTPException):
        await delete_sequence(campaign.id,email.id,BackgroundTasks(),session)
    with pytest.raises(ValidationError):
        ManualStepPatch(sent_at='2026-01-01T00:00:00')
    with pytest.raises(ValidationError):
        SequenceUpdate(manual_mode='bad')

async def test_progress_changes_invalidate_only_later_slots(session):
    from sqlalchemy import select
    from app.models import QueueSlot
    from tests.conftest import make_inbox, make_queue_slot
    campaign,lead,cl,email,manual=await setup(session)
    await make_sequence(session,campaign.id,position=2)
    inbox=await make_inbox(session)
    await make_queue_slot(session,cl.id,inbox.id,sequence_index=0)
    await make_queue_slot(session,cl.id,inbox.id,sequence_index=2)
    await update_manual_step(campaign.id,lead.id,manual.id,ManualStepPatch(sent=True),BackgroundTasks(),session)
    assert list((await session.scalars(select(QueueSlot.sequence_index))).all()) == [0]
    await make_queue_slot(session,cl.id,inbox.id,sequence_index=2)
    await update_sequence(campaign.id,manual.id,SequenceUpdate(manual_mode='ignore'),BackgroundTasks(),session)
    assert list((await session.scalars(select(QueueSlot.sequence_index))).all()) == [0]

async def test_draft_save_and_mode_edit_do_not_reactivate_completed_lead(session):
    campaign,lead,cl,email,manual=await setup(session)
    await make_sequence(session,campaign.id,position=2)
    cl.enrollment_status='completed'
    tasks=BackgroundTasks()
    await update_manual_step(campaign.id,lead.id,manual.id,ManualStepPatch(message='Draft'),tasks,session)
    assert cl.enrollment_status=='completed' and tasks.tasks==[]
    await update_sequence(campaign.id,manual.id,SequenceUpdate(manual_mode='ignore'),BackgroundTasks(),session)
    assert cl.enrollment_status=='completed'
    assert len(await list_manual_steps(campaign.id,lead_id=lead.id,sequence_id=manual.id,db=session))==1
