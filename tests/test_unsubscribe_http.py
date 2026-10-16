"""Real ASGI request parsing for public unsubscribe links."""
from datetime import datetime

import httpx
import pytest
from sqlalchemy import func, select

from app.database import get_db
from app.main import app
from app.models import LeadUnsubscribeToken, QueueSlot, UnsubscribeAudit
from tests.conftest import (
    make_campaign, make_campaign_lead, make_inbox, make_lead,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("post_kind", ["browser", "one_click_form", "one_click_multipart"])
async def test_http_get_head_and_post_unsubscribe(session, post_kind):
    inbox = await make_inbox(session)
    campaign = await make_campaign(session)
    lead = await make_lead(session)
    cl = await make_campaign_lead(session, campaign.id, lead.id)
    session.add(LeadUnsubscribeToken(
        lead_id=lead.id, campaign_id=campaign.id, token="http-unsubscribe-token"))
    session.add(QueueSlot(
        campaign_lead_id=cl.id, inbox_id=inbox.id, sequence_index=0,
        scheduled_date=datetime(2030, 1, 1), position_in_day=1))
    await session.flush()

    async def use_test_db():
        yield session
    app.dependency_overrides[get_db] = use_test_db
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            url = "/u/http-unsubscribe-token"
            get = await client.get(url)
            head = await client.head(url)
            bad = await client.post(url, data={"confirm": "yes"})
            assert get.status_code == head.status_code == 200
            assert b"Confirm unsubscribe" in get.content
            assert head.content == b""
            assert bad.status_code == 400
            await session.refresh(cl)
            assert cl.enrollment_status == "active"
            assert (await session.scalar(select(func.count(QueueSlot.id)))) == 1
            assert (await session.scalar(select(func.count(UnsubscribeAudit.id)))) == 0

            if post_kind == "one_click_multipart":
                post = await client.post(url, files={"List-Unsubscribe": (None, "One-Click")})
            elif post_kind == "one_click_form":
                post = await client.post(url, content="List-Unsubscribe=One-Click",
                                         headers={"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"})
            else:
                post = await client.post(url, data={"confirm": "unsubscribe"})
            assert post.status_code == 200
            await session.refresh(cl)
            assert cl.enrollment_status == "unsubscribed"
            assert (await session.scalar(select(func.count(QueueSlot.id)))) == 0
            audit = (await session.execute(select(UnsubscribeAudit))).scalar_one()
            assert audit.mechanism == (
                "browser_confirmation" if post_kind == "browser" else "rfc8058_one_click")
            assert audit.request_method == "POST"
            repeat = await client.post(url, data={"confirm": "unsubscribe"})
            assert repeat.status_code == 200
            assert (await session.scalar(select(func.count(UnsubscribeAudit.id)))) == 1
    finally:
        app.dependency_overrides.pop(get_db, None)
