from datetime import datetime, timezone

import pytest
from fastapi import BackgroundTasks, HTTPException
from pydantic import ValidationError

from app.models import LeadReply
from app.routers.leads import get_lead, list_leads, update_lead
from app.routers.settings import CompanyVoice, get_company_voice, set_company_voice
from app.routers.campaigns import create_campaign, update_campaign, get_campaign
from app.schemas import LeadUpdate, CampaignCreate, CampaignUpdate
from tests.conftest import make_campaign, make_lead, make_email_log, make_campaign_lead

pytestmark = pytest.mark.asyncio

async def test_profile_roundtrip_and_partial_update(session):
    lead = await make_lead(session)
    payload = LeadUpdate(priority='high', company='Acme', job_title='VP Operations', role_description='Runs delivery',
                         apollo_id='apollo-123', notes='Met at conference', linkedin_url='https://www.linkedin.com/in/alex')
    saved = await update_lead(lead.id, payload, BackgroundTasks(), session)
    assert saved.apollo_id == 'apollo-123' and saved.company == 'Acme'
    cleared = await update_lead(lead.id, LeadUpdate(notes=''), BackgroundTasks(), session)
    assert cleared.notes == ''
    assert cleared.company == 'Acme'
    assert cleared.priority == 'high' and cleared.job_title == 'VP Operations'
    assert cleared.role_description == 'Runs delivery' and cleared.apollo_id == 'apollo-123'

async def test_invalid_profile_and_naive_dates():
    for payload in [{'priority': 'urgent'}, {'linkedin_url': 'javascript:alert(1)'},
                    {'apollo_id': 'x' * 256}]:
        with pytest.raises(ValidationError): LeadUpdate(**payload)

async def test_company_and_sequence_voice(session):
    assert (await get_company_voice(session)).company_voice == ''
    await set_company_voice(CompanyVoice(company_voice='Use plain English'), session)
    campaign = await create_campaign(CampaignCreate(name='Outreach', inbox_ids=[], llm_voice='Focus on operations'), session)
    assert campaign.llm_voice == 'Focus on operations'
    await update_campaign(campaign.id, CampaignUpdate(llm_voice=''), BackgroundTasks(), session)
    assert (await get_campaign(campaign.id, session)).llm_voice == ''
    assert (await get_company_voice(session)).company_voice == 'Use plain English'

async def test_http_and_openapi_expose_outreach_to_mcp(session):
    import httpx
    from app.main import app
    from app.auth import get_current_user
    from app.database import get_db
    async def db(): yield session
    app.dependency_overrides[get_db] = db
    app.dependency_overrides[get_current_user] = lambda: object()
    try:
        lead = await make_lead(session)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            response = await client.patch(f'/api/leads/{lead.id}', json={'priority':'high', 'apollo_id':'apollo-test', 'notes':'Remember this'})
            assert response.status_code == 200
            assert response.json()['apollo_id'] == 'apollo-test'
            assert (await client.get('/api/leads?linkedin_pending=true')).status_code == 410
            spec = (await client.get('/openapi.json')).json()
            assert 'apollo_id' in spec['components']['schemas']['LeadUpdate']['properties']
            assert 'linkedin_messages' not in spec['components']['schemas']['LeadResponse']['properties']
            assert '/api/settings/llm-voice' in spec['paths']
            assert '/api/campaigns/{campaign_id}/manual-steps' in spec['paths']
    finally:
        app.dependency_overrides.clear()

async def test_bulk_and_csv_preserve_profile_and_export_messages(session):
    import csv, io, json
    from app.routers.campaigns import bulk_add_leads_to_campaign, import_campaign_leads, duplicate_campaign
    from app.routers.leads import export_leads_csv
    from app.schemas import CampaignLeadAdd
    from tests.test_pause_inbox_and_bulk_duplicates import _make_csv_upload
    campaign = await make_campaign(session, paused=True)
    campaign.llm_voice = 'Original voice'
    lead = await make_lead(session)
    lead.provider = 'Google Workspace'
    result = await bulk_add_leads_to_campaign(campaign.id,
        [CampaignLeadAdd(email=lead.email, priority='high', apollo_id='apollo-existing', notes='Keep')], db=session)
    assert result['added'] == 1 and lead.apollo_id == 'apollo-existing'
    assert (await duplicate_campaign(campaign.id, session)).llm_voice == 'Original voice'
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(['email', 'lead_job_title', 'job_title', 'priority', 'linkedin_url'])
    writer.writerow([lead.email, 'Director', 'Template title', 'VIP', 'http://linkedin.com/in/legacy'])
    await import_campaign_leads(campaign.id, _make_csv_upload(buffer.getvalue()), db=session)
    assert lead.job_title == 'Director' and lead.notes == 'Keep'
    assert lead.custom_data['job_title'] == 'Template title'
    assert lead.custom_data['priority'] == 'VIP'
    assert lead.custom_data['linkedin_url'] == 'http://linkedin.com/in/legacy'
    response = await export_leads_csv(status=None, bad_only=False, interest=None, q=None, db=session)
    content = ''.join([part async for part in response.body_iterator])
    row = next(csv.DictReader(io.StringIO(content)))
    assert row['lead_apollo_id'] == 'apollo-existing'
    assert row['job_title'] == 'Template title'
