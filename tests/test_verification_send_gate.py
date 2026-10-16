"""Verification failures must block both scheduler SQL and send-time checks."""
import pytest
from sqlalchemy import select
from app.campaign_lead_status import campaign_lead_may_receive_sends, campaign_lead_schedule_eligibility_clause
from app.models import Campaign, CampaignLead, Lead
from tests.conftest import make_campaign, make_campaign_lead, make_lead

@pytest.mark.asyncio
@pytest.mark.parametrize('status,allowed', [('pending',False), ('verification_error',False), ('invalid',False), ('risky',False), ('valid',True)])
async def test_verification_status_blocks_sql_and_send_policy(session,status,allowed):
    campaign=await make_campaign(session)
    lead=await make_lead(session)
    lead.email_verification_status=status
    enrollment=await make_campaign_lead(session,campaign.id,lead.id)
    await session.flush()
    assert campaign_lead_may_receive_sends(enrollment,lead) is allowed
    found=await session.scalar(select(CampaignLead.id).join(Lead).join(Campaign).where(CampaignLead.id==enrollment.id,campaign_lead_schedule_eligibility_clause()))
    assert (found is not None) is allowed
