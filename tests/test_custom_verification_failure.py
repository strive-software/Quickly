"""A successful HTTP response is not itself an email-verification verdict."""
import json
import pytest
from app.app_settings import (put_setting, EMAIL_VERIFICATION_ENABLED, EMAIL_VERIFICATION_PROVIDER,
    EMAIL_VERIFICATION_CUSTOM_URL, EMAIL_VERIFICATION_CUSTOM_FIELD,
    EMAIL_VERIFICATION_CUSTOM_VALID_VALUES, EMAIL_VERIFICATION_CUSTOM_INVALID_VALUES)
from app.email_verification import CustomHttpProvider
from app.routers import campaigns
from tests.conftest import make_lead

@pytest.mark.parametrize('body',[{'error':'quota exceeded'},{'result':None},{'result':''},{'result':{}},{'result':[]},{'result':'error'},{'result':'throttled'},{'result':'unknown'}])
def test_custom_missing_result_is_structured_failure(body):
    provider=CustomHttpProvider('https://checker.example.com/?email={email}','result',['valid'],['invalid'])
    result=provider._normalise('test@example.com',body)
    assert result.failed is True
    assert result.status=='unknown'

@pytest.mark.parametrize('response_body',[{'error':'quota exceeded'},{'result':'error','reason':'quota exceeded'},{'result':'throttled'},{'result':'unknown'}])
async def test_http_200_quota_error_cannot_release_new_lead(session,monkeypatch,response_body):
    lead=await make_lead(session)
    lead.email_verification_status='pending'
    for key,value in ((EMAIL_VERIFICATION_ENABLED,'true'),(EMAIL_VERIFICATION_PROVIDER,'custom'),
        (EMAIL_VERIFICATION_CUSTOM_URL,'https://checker.example.com/?email={email}'),
        (EMAIL_VERIFICATION_CUSTOM_FIELD,'result'),(EMAIL_VERIFICATION_CUSTOM_VALID_VALUES,json.dumps(['valid'])),
        (EMAIL_VERIFICATION_CUSTOM_INVALID_VALUES,json.dumps(['invalid']))):
        await put_setting(session,key,value)
    await session.commit()
    monkeypatch.setattr(campaigns,'_verification_last_check_at',None)
    class Response:
        status_code=200
        def json(self):return response_body
    class Client:
        def __init__(self,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def get(self,*args,**kwargs):return Response()
    monkeypatch.setattr('app.email_verification.httpx.AsyncClient',Client)
    async def forbid_schedule(*args,**kwargs):
        raise AssertionError('Unverified provider errors must not be scheduled')
    monkeypatch.setattr('app.queue_logic.reserve_slots_for_new_leads_bulk',forbid_schedule)
    await campaigns._run_background_verification([lead.id])
    await session.refresh(lead)
    assert lead.email_verification_status=='verification_error'
    assert 'error' in lead.email_verification_result

@pytest.mark.parametrize('body,expected', [({'result':'valid'},True),({'result':'invalid'},True),({'result':'error'},False),({'error':'quota exceeded'},False)])
async def test_custom_checker_health_requires_mapped_response(session,monkeypatch,body,expected):
    from app.routers.settings import test_custom_email_verification, _CustomProviderTestRequest
    from app.app_settings import get_setting, EMAIL_VERIFICATION_CONNECTION_TESTED
    async def fake_verify(self,email,api_key):
        return self._normalise(email,body)
    monkeypatch.setattr(CustomHttpProvider,'verify',fake_verify)
    result=await test_custom_email_verification(_CustomProviderTestRequest(
        url_template='https://checker.example.com/?email={email}',field_path='result',
        valid_values=['valid'],invalid_values=['invalid'],test_emails=['test@example.com']),session)
    assert result['connection_tested'] is expected
    assert await get_setting(session,EMAIL_VERIFICATION_CONNECTION_TESTED)==('true' if expected else 'false')

async def test_custom_url_preview_does_not_replace_live_checker(session,monkeypatch):
    from app.routers.settings import test_custom_email_verification, _CustomProviderTestRequest
    from app.app_settings import get_setting, EMAIL_VERIFICATION_CONNECTION_TESTED
    await put_setting(session,EMAIL_VERIFICATION_CUSTOM_URL,'https://existing.example.com/?email={email}')
    await put_setting(session,EMAIL_VERIFICATION_CONNECTION_TESTED,'true')
    await session.commit()
    async def fake_verify(self,email,api_key):
        return self._normalise(email,{'status':'valid'})
    monkeypatch.setattr(CustomHttpProvider,'verify',fake_verify)
    result=await test_custom_email_verification(_CustomProviderTestRequest(
        url_template='https://preview.example.com/?email={email}',test_emails=['test@example.com'],
        persist_configuration=False),session)
    assert result['results'][0]['raw_response']=={'status':'valid'}
    assert await get_setting(session,EMAIL_VERIFICATION_CONNECTION_TESTED)=='true'
    assert await get_setting(session,EMAIL_VERIFICATION_CUSTOM_URL)=='https://existing.example.com/?email={email}'
