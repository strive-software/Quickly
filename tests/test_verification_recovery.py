"""Recovery of durable pending verification work after an app restart."""
import asyncio
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import select

from app import main
from app.models import Lead
from tests.conftest import make_lead
from tests.test_send_auth_failure import _SessionCtx


@pytest.mark.asyncio
async def test_recovery_dispatches_only_bounded_pending_ids(session, monkeypatch):
    leads = [await make_lead(session, email=f"pending-{i}@example.com") for i in range(102)]
    for lead in leads:
        lead.email_verification_status = "pending"
    leads[0].email_verification_status = "valid"
    await session.flush()

    received = []
    async def fake_verify(ids):
        received.append(ids)
    monkeypatch.setattr("app.database.AsyncSessionLocal", lambda: _SessionCtx(session))
    monkeypatch.setattr(main.campaigns, "_run_background_verification", fake_verify)

    await main.resume_pending_verifications()
    assert len(received) == 1
    assert received[0] == [lead.id for lead in leads[1:101]]
    assert (await session.execute(select(Lead.email_verification_status).where(
        Lead.id == leads[-1].id))).scalar_one() == "pending"


@pytest.mark.asyncio
async def test_lifespan_schedules_nonblocking_recovery(session, monkeypatch):
    started = asyncio.Event()
    release = asyncio.Event()
    class FakeSchedule:
        def __init__(self, *args, **kwargs):
            self.jobs = {}
        def add_job(self, func, trigger, **kwargs):
            self.jobs[kwargs["id"]] = (func, trigger, kwargs)
        def start(self):
            pass
        def shutdown(self):
            pass

    async def fake_recover():
        started.set()
        await release.wait()
    async def fake_init():
        pass
    async def fake_sync(*args, **kwargs):
        pass
    async def fake_cfg(db):
        return {"sync_interval_minutes": 5}
    @asynccontextmanager
    async def fake_mcp():
        yield

    monkeypatch.setattr(main, "init_db", fake_init)
    monkeypatch.setattr(main, "AsyncIOScheduler", FakeSchedule)
    monkeypatch.setattr(main.scheduler_mod, "build_jobstores", lambda url: {})
    monkeypatch.setattr(main, "queue_sync_for_all_inboxes", fake_sync)
    monkeypatch.setattr(main, "resume_pending_verifications", fake_recover)
    monkeypatch.setattr("app.database.AsyncSessionLocal", lambda: _SessionCtx(session))
    monkeypatch.setattr("app.app_settings.get_gmail_sync_config", fake_cfg)
    monkeypatch.setattr("app.mcp_leads.leads_mcp_lifespan", fake_mcp)
    monkeypatch.setattr("app.backup_schedule.register_scheduled_backup_from_db", fake_sync)

    async with main.lifespan(main.app):
        await asyncio.wait_for(started.wait(), timeout=1)
        func, trigger, opts = main.app.state.schedule.jobs["verification_recovery"]
        assert func is fake_recover
        assert trigger == "interval"
        assert opts["minutes"] == 5
        assert opts["max_instances"] == 1
        assert not release.is_set()  # startup reached yield while recovery was still running
        release.set()
