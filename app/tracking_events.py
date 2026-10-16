"""Shared email tracking side effects (open, click, unsubscribe).

Used by the public tracking router and the Beacon ingest endpoint.
"""
from __future__ import annotations

# // BEACON SYNC: This file handles tracking logic that Beacon mirrors.
# // Any changes to tracking behavior, event types, metadata collected, or URL structure
# // must also be reflected in the Beacon service (/beacon or the separate Beacon repo).
# // If you are an AI agent, add a TODO at the end of your response listing what needs to be updated in Beacon.

import logging
from typing import TYPE_CHECKING

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import time as time_provider
from app.models import (
    CampaignLead,
    EmailClick,
    EmailLog,
    EmailOpen,
    KnownIP,
    Lead,
    LeadUnsubscribeToken,
    UnconfirmedUnsubscribeRequest,
    UnsubscribeAudit,
    QueueSlot,
    TrackedLink,
)
from app.webhooks import fire_webhook_event

if TYPE_CHECKING:
    pass

log = logging.getLogger("quickly.tracking_events")

_UNSUBSCRIBE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Unsubscribed</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
           display: flex; align-items: center; justify-content: center;
           min-height: 100vh; margin: 0; background: #f9fafb; }
    .card { background: #fff; border-radius: 12px; padding: 48px 40px;
            box-shadow: 0 4px 24px rgba(0,0,0,.08); text-align: center; max-width: 420px; }
    .icon { font-size: 48px; margin-bottom: 16px; }
    h1 { margin: 0 0 8px; font-size: 24px; color: #111; }
    p  { color: #555; margin: 0; }
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">✓</div>
    <h1>You've been unsubscribed</h1>
    <p>You will no longer receive emails from us.<br>
       If this was a mistake please contact the sender directly.</p>
  </div>
</body>
</html>"""

ALREADY_UNSUBSCRIBED_HTML = _UNSUBSCRIBE_HTML.replace(
    "You've been unsubscribed",
    "Already unsubscribed",
).replace(
    "You will no longer receive emails from us.<br>If this was a mistake please contact the sender directly.",
    "You are already unsubscribed and will not receive any more emails from us.",
)

INVALID_UNSUBSCRIBE_HTML = "<p>Invalid or expired unsubscribe link.</p>"

CONFIRM_UNSUBSCRIBE_HTML = """<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Confirm unsubscribe</title></head><body>
<main><h1>Unsubscribe from this campaign?</h1>
<p>Confirm to stop future emails from this campaign.</p>
<form method="post"><button type="submit" name="confirm" value="unsubscribe">Confirm unsubscribe</button></form>
</main></body></html>"""


async def is_known_ip(db: AsyncSession, ip: str | None) -> bool:
    if not ip:
        return False
    now = time_provider.utcnow()
    result = await db.execute(
        select(KnownIP).where(
            KnownIP.ip_address == ip,
            (KnownIP.permanent == True) | (KnownIP.expires_at > now),  # noqa: E712
        )
    )
    return result.scalar_one_or_none() is not None


async def resolve_email_log_for_open(db: AsyncSession, token: str) -> EmailLog | None:
    result = await db.execute(select(EmailLog).where(EmailLog.open_token == token))
    email_log = result.scalar_one_or_none()
    if email_log is None:
        try:
            log_id = int(token)
            result = await db.execute(select(EmailLog).where(EmailLog.id == log_id))
            email_log = result.scalar_one_or_none()
        except (ValueError, TypeError):
            pass
    return email_log


async def record_email_open(db: AsyncSession, token: str, ip: str | None) -> bool:
    """Persist open event if applicable. Returns True if an open was recorded."""
    email_log = await resolve_email_log_for_open(db, token)
    if not email_log:
        return False
    if await is_known_ip(db, ip):
        log.debug("open: skipping known IP %s for log_id=%s", ip, email_log.id)
        return False
    if not email_log.opened:
        email_log.opened = True
    db.add(
        EmailOpen(
            email_log_id=email_log.id,
            ip_address=ip,
            opened_at=time_provider.utcnow(),
        )
    )
    await db.commit()
    await fire_webhook_event(
        db,
        "email.opened",
        {
            "email_log_id": email_log.id,
            "lead_id": email_log.lead_id,
            "campaign_id": email_log.campaign_id,
            "ip_address": ip,
            "timestamp": time_provider.utcnow().isoformat() + "Z",
        },
    )
    return True


async def resolve_click_redirect_url(db: AsyncSession, token: str) -> str | None:
    result = await db.execute(select(TrackedLink).where(TrackedLink.token == token))
    tracked = result.scalar_one_or_none()
    if not tracked:
        return None
    return tracked.original_url


async def record_email_click(db: AsyncSession, token: str, ip: str | None) -> bool:
    """Record click when TrackedLink exists and rules allow. Returns True if recorded."""
    result = await db.execute(select(TrackedLink).where(TrackedLink.token == token))
    tracked = result.scalar_one_or_none()
    if not tracked:
        return False
    email_log_result = await db.execute(select(EmailLog).where(EmailLog.id == tracked.email_log_id))
    email_log = email_log_result.scalar_one_or_none()
    if not email_log:
        return False
    if await is_known_ip(db, ip):
        log.debug("click: skipping known IP %s for log_id=%s", ip, email_log.id)
        return False
    if not email_log.clicked:
        email_log.clicked = True
    db.add(
        EmailClick(
            email_log_id=tracked.email_log_id,
            ip_address=ip,
            clicked_at=time_provider.utcnow(),
        )
    )
    await db.commit()
    await fire_webhook_event(
        db,
        "email.clicked",
        {
            "email_log_id": tracked.email_log_id,
            "lead_id": email_log.lead_id,
            "campaign_id": email_log.campaign_id,
            "original_url": tracked.original_url,
            "ip_address": ip,
            "timestamp": time_provider.utcnow().isoformat() + "Z",
        },
    )
    return True


async def unsubscribe_page(db: AsyncSession, token: str) -> tuple[str, int]:
    """Read-only link landing page, including for mail scanner GET/HEAD requests."""
    result = await db.execute(select(LeadUnsubscribeToken).where(LeadUnsubscribeToken.token == token))
    row = result.scalar_one_or_none()
    if not row:
        return INVALID_UNSUBSCRIBE_HTML, 404
    cl_res = await db.execute(select(CampaignLead).where(
        CampaignLead.lead_id == row.lead_id, CampaignLead.campaign_id == row.campaign_id,
    ))
    cl = cl_res.scalar_one_or_none()
    if cl is None:
        return INVALID_UNSUBSCRIBE_HTML, 404
    if cl.enrollment_status == "unsubscribed":
        return ALREADY_UNSUBSCRIBED_HTML, 200
    return CONFIRM_UNSUBSCRIBE_HTML, 200


async def process_unsubscribe(
    db: AsyncSession, token: str, *, ip_address: str | None = None,
    user_agent: str | None = None, mechanism: str,
) -> tuple[str, int]:
    """Apply a validated POST action; return (html_body, http_status)."""
    result = await db.execute(select(LeadUnsubscribeToken).where(LeadUnsubscribeToken.token == token))
    row = result.scalar_one_or_none()
    if not row:
        return INVALID_UNSUBSCRIBE_HTML, 404

    changed, old_status = await _apply_confirmed_unsubscribe(
        db, row.lead_id, row.campaign_id, ip_address=ip_address,
        user_agent=user_agent, mechanism=mechanism,
    )
    if old_status is None:
        return INVALID_UNSUBSCRIBE_HTML, 404
    await db.commit()
    if changed:
        await emit_unsubscribe_webhooks(db, row.lead_id, row.campaign_id,
                                        old_status=old_status, mechanism=mechanism)
    return (_UNSUBSCRIBE_HTML if changed else ALREADY_UNSUBSCRIBED_HTML), 200


async def _apply_confirmed_unsubscribe(
    db: AsyncSession, lead_id: int, campaign_id: int, *,
    ip_address: str | None, user_agent: str | None, mechanism: str,
) -> tuple[bool, str | None]:
    """Change campaign state and queue in the caller's transaction."""
    cl_res = await db.execute(
        select(CampaignLead).where(
            CampaignLead.lead_id == lead_id,
            CampaignLead.campaign_id == campaign_id,
        ).with_for_update().execution_options(populate_existing=True)
    )
    cl = cl_res.scalar_one_or_none()
    if not cl:
        return False, None
    # An earlier legacy Beacon event may have created a review hold. A later
    # confirmed POST supplies the missing proof and closes that request in the
    # same transaction as the unsubscribe transition.
    pending = await db.scalar(select(UnconfirmedUnsubscribeRequest).where(
        UnconfirmedUnsubscribeRequest.lead_id == lead_id,
        UnconfirmedUnsubscribeRequest.campaign_id == campaign_id,
        UnconfirmedUnsubscribeRequest.reviewed_at.is_(None),
    ).with_for_update())
    if pending is not None:
        pending.reviewed_at = time_provider.utcnow()
        pending.review_decision = "confirmed"
    old_status = cl.enrollment_status
    changed = old_status != "unsubscribed"
    if changed:
        cl.enrollment_status = "unsubscribed"
        cl.interest_status = None
        db.add(UnsubscribeAudit(
            lead_id=lead_id, campaign_id=campaign_id,
            occurred_at=time_provider.utcnow(), request_method="POST",
            ip_address=ip_address[:45] if ip_address else None,
            user_agent=user_agent[:512] if user_agent else None,
            mechanism=mechanism,
        ))
        log.info("Unsubscribed lead_id=%s campaign_id=%s mechanism=%s",
                 lead_id, campaign_id, mechanism)
    await db.execute(delete(QueueSlot).where(QueueSlot.campaign_lead_id == cl.id))
    return changed, old_status


async def confirm_unsubscribe_request(
    db: AsyncSession, request_row: UnconfirmedUnsubscribeRequest,
) -> str | None:
    """Apply an operator's accepted review without committing the review row."""
    changed, old_status = await _apply_confirmed_unsubscribe(
        db, request_row.lead_id, request_row.campaign_id,
        ip_address=request_row.ip_address, user_agent=request_row.user_agent,
        mechanism="operator_confirmation",
    )
    return old_status if changed else None


async def emit_unsubscribe_webhooks(
    db: AsyncSession, lead_id: int, campaign_id: int, *,
    old_status: str, mechanism: str,
) -> None:
    lead = await db.scalar(select(Lead).where(Lead.id == lead_id))
    data = {
        "lead_id": lead_id, "lead_email": lead.email if lead else "",
        "campaign_id": campaign_id, "mechanism": mechanism,
        "request_method": "POST", "timestamp": time_provider.utcnow().isoformat() + "Z",
    }
    await fire_webhook_event(db, "lead.unsubscribed", data)
    await fire_webhook_event(db, "lead.status_changed", {
        **data, "old_enrollment_status": old_status,
        "new_enrollment_status": "unsubscribed",
    })
