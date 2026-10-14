"""Manual LinkedIn steps; these endpoints record work, never send messages."""
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Campaign, CampaignLead, EmailLog, Lead, LeadReply, ManualStepRecord, QueueSlot, Sequence
from app.schemas import ManualStepPatch, ManualStepResponse
from app.queue_logic import manual_step_resolved, refresh_manual_enrollment, next_business_date, _get_tz

router = APIRouter()


def _utc(value):
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


def _response(cl, lead, step, record, ready=False):
    return ManualStepResponse(campaign_lead_id=cl.id, lead_id=lead.id, name=lead.name or '',
        email=lead.email, priority=lead.priority, linkedin_url=lead.linkedin_url,
        sequence_id=step.id, position=step.position, mode=step.manual_mode, ready=ready,
        message=record.message if record else step.body or '',
        sent=bool(record and record.sent_at), sent_at=_utc(record.sent_at) if record else None,
        ignored=bool(record and record.ignored))


@router.get('/{campaign_id}/manual-steps', response_model=list[ManualStepResponse])
async def list_manual_steps(campaign_id: int, ready_only: bool = False,
    priority: Literal['low', 'normal', 'high'] | None = None,
    has_sent_email: bool | None = None, lead_id: int | None = None,
    sequence_id: int | None = None, db: AsyncSession = Depends(get_db)):
    """List campaign LinkedIn work. ready_only excludes Done, explicitly skipped, paused and suppressed work.
    Campaign Ignore mode bypasses email blocking but still exposes pending manual work.

    Combine ready_only, priority=high and has_sent_email=true for outreach suggestions.
    Email history and completion are scoped to this campaign, not other enrollments.
    """
    campaign = await db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(404, 'Campaign not found')
    steps = list((await db.scalars(select(Sequence).where(Sequence.campaign_id == campaign_id).order_by(Sequence.position))).all())
    enrollment_query = select(CampaignLead, Lead).join(Lead).where(CampaignLead.campaign_id == campaign_id)
    if lead_id is not None:
        enrollment_query = enrollment_query.where(Lead.id == lead_id)
    rows = (await db.execute(enrollment_query)).all()
    cl_ids = [cl.id for cl, _ in rows]
    lead_ids = [lead.id for _, lead in rows]
    records = {(r.campaign_lead_id, r.sequence_id): r for r in (await db.scalars(
        select(ManualStepRecord).where(ManualStepRecord.campaign_lead_id.in_(cl_ids)))).all()}
    logs = {}
    for item in (await db.execute(select(EmailLog.lead_id, EmailLog.sequence_index, EmailLog.sent_at).where(
        EmailLog.campaign_id == campaign_id, EmailLog.lead_id.in_(lead_ids)))).all():
        logs.setdefault(item.lead_id, {})[item.sequence_index] = _utc(item.sent_at)
    replied = set((await db.scalars(select(LeadReply.lead_id).where(LeadReply.campaign_id == campaign_id))).all())
    result = []
    zone = _get_tz(campaign.timezone) or timezone.utc
    today = datetime.now(zone).date()
    for cl, lead in rows:
        sent = logs.get(lead.id, {})
        last_email = max(sent, default=-1)
        if priority is not None and priority != lead.priority:
            continue
        if has_sent_email is not None and bool(sent) != has_sent_email:
            continue
        eligible = (not campaign.paused and not cl.sending_paused
            and cl.enrollment_status not in {'bounced', 'unsubscribed', 'wrong_person', 'invalid', 'replied'}
            and lead.status not in {'unsubscribed', 'bounced', 'invalid', 'replied'}
            and cl.interest_status not in {'not_interested', 'out_of_office'}
            and lead.email_verification_status not in {'invalid', 'risky'}
            and lead.id not in replied)
        previous_done = True
        anchor = _utc(cl.enrolled_at)
        for step in steps:
            record = records.get((cl.id, step.id))
            if step.sequence_type != 'linkedin':
                previous_done = previous_done and step.position <= last_email
                if step.position in sent:
                    anchor = sent[step.position]
                continue
            resolved = manual_step_resolved(step, record)
            ready = (eligible and previous_done and not (record and (record.sent_at or record.ignored))
                and today >= next_business_date(anchor.astimezone(zone).date(),
                    campaign.sending_days or [0, 1, 2, 3, 4],
                    step.wait_days_after_previous if step.manual_mode == "hold" else 0))
            if (sequence_id is None or step.id == sequence_id) and (not ready_only or ready):
                result.append(_response(cl, lead, step, record, ready))
            previous_done = previous_done and resolved
            if record and record.sent_at and step.manual_mode != 'ignore' and not record.ignored:
                anchor = max(anchor, _utc(record.sent_at))
    return result


@router.patch('/{campaign_id}/leads/{lead_id}/manual-steps/{sequence_id}', response_model=ManualStepResponse)
async def update_manual_step(campaign_id: int, lead_id: int, sequence_id: int,
    data: ManualStepPatch, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    """Save draft or mark Pending/Done. Ignore is independent of sent state.

    sent=true records now unless a timezone-aware sent_at is supplied; false clears it.
    ignored=true skips a held step for this enrollment without marking it sent.
    """
    cl = (await db.scalars(select(CampaignLead).where(CampaignLead.campaign_id == campaign_id,
        CampaignLead.lead_id == lead_id).with_for_update())).one_or_none()
    step = await db.get(Sequence, sequence_id)
    if cl is None or step is None or step.campaign_id != campaign_id or step.sequence_type != 'linkedin':
        raise HTTPException(404, 'Manual step or campaign enrollment not found')
    changes = data.model_dump(exclude_unset=True)
    if any(changes.get(key, False) is None for key in ('message', 'sent', 'ignored')):
        raise HTTPException(422, 'Message, sent and ignored cannot be null')
    if 'sent' in changes and 'sent_at' in changes and data.sent != bool(data.sent_at):
        raise HTTPException(422, 'Sent and sent_at disagree')
    record = (await db.scalars(select(ManualStepRecord).where(
        ManualStepRecord.campaign_lead_id == cl.id, ManualStepRecord.sequence_id == step.id))).one_or_none()
    previous_progress = (_utc(record.sent_at), bool(record.ignored)) if record else (None, False)
    if record is None and not changes:
        rows = await list_manual_steps(campaign_id, lead_id=lead_id, sequence_id=sequence_id, db=db)
        return rows[0]
    if record is None:
        record = ManualStepRecord(campaign_lead_id=cl.id, sequence_id=step.id, message=step.body or '')
        db.add(record)
    if 'message' in changes:
        record.message = data.message
    if 'ignored' in changes:
        record.ignored = data.ignored
    if 'sent_at' in changes:
        record.sent_at = data.sent_at
    if data.sent is not None:
        record.sent_at = (record.sent_at or datetime.now(timezone.utc)) if data.sent else None
    if record.sent_at and not record.message.strip():
        raise HTTPException(422, 'A sent message must have text')
    await db.flush()
    progression_changed = previous_progress != (_utc(record.sent_at), bool(record.ignored))
    if progression_changed:
        await refresh_manual_enrollment(db, cl)
        await db.execute(delete(QueueSlot).where(QueueSlot.campaign_lead_id == cl.id,
            QueueSlot.sequence_index >= step.position))
    await db.commit()
    from app.routers.schedule import enqueue_global_recalculate
    if progression_changed:
        enqueue_global_recalculate(background_tasks)
    rows = await list_manual_steps(campaign_id, lead_id=lead_id, sequence_id=sequence_id, db=db)
    return next(row for row in rows if row.campaign_lead_id == cl.id and row.sequence_id == step.id)
