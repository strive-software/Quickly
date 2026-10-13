"""Unclassified replies count; automatic and out-of-office replies do not."""
from datetime import datetime

import pytest

from app.models import LeadReply
from app.routers.analytics import daily_analytics
from app.routers.campaigns import get_campaign, list_campaigns
from tests.conftest import make_campaign, make_lead, make_campaign_lead


@pytest.mark.asyncio
@pytest.mark.parametrize("interest,expected", [(None, 1), ("interested", 1), ("not_interested", 1), ("auto_reply", 0), ("out_of_office", 0)])
@pytest.mark.parametrize("endpoint", ["daily", "detail", "list"])
async def test_reply_counts(session, interest, expected, endpoint):
    if endpoint == "daily" and session.bind.dialect.name != "postgresql":
        pytest.skip("Daily date aggregation requires PostgreSQL")
    campaign = await make_campaign(session)
    lead = await make_lead(session)
    enrollment = await make_campaign_lead(session, campaign.id, lead.id)
    enrollment.interest_status = interest
    session.add(LeadReply(lead_id=lead.id, campaign_id=campaign.id,
                          replied_at=datetime(2026, 10, 13, 12)))
    await session.flush()
    if endpoint == "daily":
        rows = await daily_analytics("2026-10-13", "2026-10-13", [campaign.id], session)
        assert sum(row["total_replies"] for row in rows) == expected
    elif endpoint == "detail":
        result = await get_campaign(campaign.id, session)
        assert result.stats.replies == expected
    else:
        results = await list_campaigns(session)
        assert next(row for row in results if row.id == campaign.id).stats.replies == expected
