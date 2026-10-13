from datetime import datetime, timezone

import pytest
from fastapi import BackgroundTasks, HTTPException
from pydantic import ValidationError

from app.models import LeadReply
from app.routers.leads import get_lead, list_leads, update_lead, update_linkedin_message
from app.routers.settings import CompanyVoice, get_company_voice, set_company_voice
from app.routers.campaigns import create_campaign, update_campaign, get_campaign
from app.schemas import LeadUpdate, LinkedInMessagePatch, CampaignCreate, CampaignUpdate
from tests.conftest import make_campaign, make_lead, make_email_log, make_campaign_lead

pytestmark = pytest.mark.asyncio

async def test_profile_roundtrip_and_partial_update(session):
    lead = await make_lead(session)
    payload = LeadUpdate(priority='high', job_title='VP Operations', role_description='Runs delivery',
                         apollo_id='apollo-123', notes='Met at conference', linkedin_url='https://www.linkedin.com/in/alex',
                         linkedin_replied_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    saved = await update_lead(lead.id, payload, BackgroundTasks(), session)
    assert saved.apollo_id == 'apollo-123'
    assert saved.linkedin_replied_at.tzinfo is not None
    cleared = await update_lead(lead.id, LeadUpdate(notes='', linkedin_replied_at=None), BackgroundTasks(), session)
    assert cleared.notes == '' and cleared.linkedin_replied_at is None
    assert cleared.priority == 'high' and cleared.job_title == 'VP Operations'
    assert cleared.role_description == 'Runs delivery' and cleared.apollo_id == 'apollo-123'

async def test_linkedin_slots_toggle_and_backdate(session):
    lead = await make_lead(session)
    for position in (1, 2, 3):
        await update_linkedin_message(lead.id, position, LinkedInMessagePatch(message=f'Message {position}'), session)
    sent = await update_linkedin_message(lead.id, 2, LinkedInMessagePatch(sent=True), session)
    assert sent.sent and sent.sent_at.tzinfo
    repeated = await update_linkedin_message(lead.id, 2, LinkedInMessagePatch(sent=True), session)
    assert repeated.sent_at == sent.sent_at
    at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    historical = await update_linkedin_message(lead.id, 2, LinkedInMessagePatch(sent_at=at), session)
    assert historical.sent_at == at
    unsent = await update_linkedin_message(lead.id, 2, LinkedInMessagePatch(sent=False), session)
    assert not unsent.sent and unsent.sent_at is None
    assert lead.linkedin_messages[0]['message'] == 'Message 1'
    assert lead.linkedin_messages[2]['message'] == 'Message 3'

@pytest.mark.parametrize('position,payload', [(4, {}), (0, {}), (1, {'sent': True}),
    (1, {'sent': None}), (1, {'message': None}), (1, {'sent': False, 'sent_at': '2026-01-01T00:00:00Z'})])
async def test_invalid_linkedin_updates(session, position, payload):
    lead = await make_lead(session)
    with pytest.raises(HTTPException) as error:
        await update_linkedin_message(lead.id, position, LinkedInMessagePatch(**payload), session)
    assert error.value.status_code == 422

async def test_invalid_profile_and_naive_dates():
    for payload in [{'priority': 'urgent'}, {'linkedin_url': 'javascript:alert(1)'},
                    {'apollo_id': 'x' * 256}, {'linkedin_replied_at': '2026-01-01T00:00:00'}]:
        with pytest.raises(ValidationError): LeadUpdate(**payload)

async def test_pending_filters(session):
    campaign = await make_campaign(session)
    leads = []
    for index in range(9):
        lead = await make_lead(session, email=f'lead{index}@example.com')
        lead.priority = 'high'
        lead.linkedin_messages = [{'message': 'Hello', 'sent': False, 'sent_at': None}]
        if index != 1: await make_email_log(session, lead.id, campaign.id)
        leads.append(lead)
    leads[2].priority = 'normal'
    leads[3].linkedin_paused = True
    leads[4].linkedin_replied_at = datetime.now(timezone.utc)
    leads[5].linkedin_messages = [{'message': 'Hello', 'sent': True, 'sent_at': datetime.now(timezone.utc).isoformat()}]
    leads[6].linkedin_messages = []
    session.add(LeadReply(lead_id=leads[7].id, campaign_id=campaign.id))
    enrollment = await make_campaign_lead(session, campaign.id, leads[8].id)
    enrollment.enrollment_status = "wrong_person"
    await session.flush()
    rows = await list_leads(status=None, bad_only=False, interest=None, q=None, linkedin_pending=True, db=session)
    assert [r.id for r in rows] == [leads[0].id]
    assert rows[0].last_email_sent_at is not None
    assert (await get_lead(leads[1].id, session)).last_email_sent_at is None
    rows = await list_leads(status=None, bad_only=False, interest=None, q=None, has_sent_email=False, db=session)
    assert [r.id for r in rows] == [leads[1].id]

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
            result = await client.patch(f'/api/leads/{lead.id}/linkedin/1', json={'message':'Hello', 'sent':True})
            assert result.status_code == 200 and result.json()['sent_at'].endswith('Z')
            assert (await client.patch(f'/api/leads/{lead.id}/linkedin/4', json={})).status_code == 422
            spec = (await client.get('/openapi.json')).json()
            assert 'apollo_id' in spec['components']['schemas']['LeadUpdate']['properties']
            assert 'linkedin_messages' in spec['components']['schemas']['LeadResponse']['properties']
            assert '/api/settings/llm-voice' in spec['paths']
            assert 'linkedin_pending' in {x['name'] for x in spec['paths']['/api/leads']['get']['parameters']}
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
    writer.writerow(['email', 'lead_job_title', 'lead_linkedin_paused', 'lead_linkedin_messages', 'job_title', 'priority', 'linkedin_url'])
    writer.writerow([lead.email, 'Director', 'false', json.dumps([{'message':'Draft', 'sent':False}]), 'Template title', 'VIP', 'http://linkedin.com/in/legacy'])
    await import_campaign_leads(campaign.id, _make_csv_upload(buffer.getvalue()), db=session)
    assert lead.job_title == 'Director' and lead.notes == 'Keep'
    assert lead.linkedin_messages[0]['message'] == 'Draft'
    assert lead.custom_data['job_title'] == 'Template title'
    assert lead.custom_data['priority'] == 'VIP'
    assert lead.custom_data['linkedin_url'] == 'http://linkedin.com/in/legacy'
    response = await export_leads_csv(status=None, bad_only=False, interest=None, q=None, db=session)
    content = ''.join([part async for part in response.body_iterator])
    row = next(csv.DictReader(io.StringIO(content)))
    assert row['lead_apollo_id'] == 'apollo-existing'
    assert json.loads(row['lead_linkedin_messages'])[0]['message'] == 'Draft'
    assert row['job_title'] == 'Template title'
