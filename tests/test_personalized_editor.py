"""The editor must be able to reopen saved personalized email content."""
import pytest
from app.models import CustomEmailOverride
from app.routers.campaigns import list_campaign_leads
from tests.conftest import make_campaign, make_sequence, make_lead, make_campaign_lead


@pytest.mark.parametrize("body,is_html", [("Hello\nA personal note", False), ("<p>Hello <strong>Alex</strong></p>", True)])
async def test_editor_receives_saved_body_and_format(session, body, is_html):
    campaign = await make_campaign(session, paused=True)
    sequence = await make_sequence(session, campaign.id, sequence_type="personalized")
    lead = await make_lead(session)
    enrollment = await make_campaign_lead(session, campaign.id, lead.id)
    session.add(CustomEmailOverride(campaign_lead_id=enrollment.id,
        sequence_id=sequence.id, subject="Personal subject", body=body, is_html=is_html))
    await session.flush()
    result = await list_campaign_leads(campaign.id, db=session)
    saved = result[0]["personalized"][0]
    assert saved["written"] is True
    assert saved["subject"] == "Personal subject"
    assert saved["body"] == body
    assert saved["is_html"] is is_html


async def test_unwritten_email_has_no_saved_content(session):
    campaign = await make_campaign(session, paused=True)
    await make_sequence(session, campaign.id, sequence_type="personalized")
    lead = await make_lead(session)
    await make_campaign_lead(session, campaign.id, lead.id)
    result = await list_campaign_leads(campaign.id, db=session)
    saved = result[0]["personalized"][0]
    assert saved["written"] is False
    assert saved["body"] is None
    assert saved["is_html"] is None
