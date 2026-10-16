"""Concurrent scanner-safe confirmations preserve a single audit transition."""
import asyncio
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker
from app.models import UnsubscribeAudit, QueueSlot
from app.tracking_events import process_unsubscribe
from tests.conftest import make_campaign, make_campaign_lead, make_lead, make_inbox, make_queue_slot, make_unsubscribe_token

async def test_concurrent_post_confirms_once(engine, session, monkeypatch):
    if engine.dialect.name != 'postgresql':
        pytest.skip('PostgreSQL row-lock semantics required')
    campaign=await make_campaign(session)
    lead=await make_lead(session)
    enrollment=await make_campaign_lead(session,campaign.id,lead.id)
    inbox=await make_inbox(session)
    await make_queue_slot(session,enrollment.id,inbox.id,0)
    token=await make_unsubscribe_token(session,lead.id,campaign.id,token='concurrent-confirm-test')
    await session.commit()
    async def no_webhook(*args,**kwargs):
        pass
    monkeypatch.setattr('app.tracking_events.fire_webhook_event',no_webhook)
    factory=async_sessionmaker(engine,expire_on_commit=False)
    async def confirm():
        async with factory() as db:
            return await process_unsubscribe(db,token.token,mechanism='rfc8058_one_click')
    responses=await asyncio.gather(confirm(),confirm())
    assert all(status==200 for _,status in responses)
    async with factory() as db:
        assert await db.scalar(select(func.count()).select_from(UnsubscribeAudit))==1
        assert await db.scalar(select(func.count()).select_from(QueueSlot))==0
