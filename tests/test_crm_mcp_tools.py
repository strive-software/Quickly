"""Exercise the MCP protocol boundary without network credentials or sends."""
import json
import httpx
from mcp.shared.memory import create_connected_server_and_client_session
from app import mcp_leads

async def test_crm_mcp_routes_preserve_revision_tokens_and_unpublished_copy(monkeypatch):
    seen=[]
    async def handle(request):
        seen.append((request.method,request.url.path,dict(request.url.params),json.loads(request.content) if request.content else None))
        return httpx.Response(200,json={'ok':True},request=request)
    original_client=httpx.AsyncClient
    monkeypatch.setattr(mcp_leads,'_outbound_headers',lambda ctx:{'X-API-Key':'synthetic-test-key'})
    monkeypatch.setattr(mcp_leads.httpx,'AsyncClient',lambda *args,**kwargs:original_client(*args,transport=httpx.MockTransport(handle),**kwargs))
    async with create_connected_server_and_client_session(mcp_leads.leads_mcp) as client:
        await client.call_tool('get_lead_research',{'lead_id':7})
        await client.call_tool('save_lead_research',{'lead_id':7,'summary':'Verified role','sources':[{'url':'https://example.com/role'}],'expected_updated_at':'2026-10-16T12:00:00Z'})
        await client.call_tool('get_lead_emails',{'lead_id':7,'campaign_id':3})
        await client.call_tool('save_personalized_email_draft',{'campaign_id':3,'lead_id':7,'sequence_id':11,'subject':None,'body':'Hello {{name}}','is_html':False,'expected_updated_at':None})
        assert not any(path.endswith('/release') for _,path,_,_ in seen)
        await client.call_tool('release_personalized_email_draft',{'campaign_id':3,'lead_id':7,'sequence_id':11,'expected_updated_at':'2026-10-16T12:01:00Z'})
        await client.call_tool('retry_lead_verification',{'lead_id':7})
        await client.call_tool('review_unconfirmed_unsubscribe',{'lead_id':7,'request_id':9,'decision':'rejected'})
    assert seen[1][0:2]==('PUT','/api/leads/7/research')
    assert seen[1][3]['expected_updated_at']=='2026-10-16T12:00:00Z'
    assert seen[2][2]=={'campaign_id':'3'}
    assert seen[3][3]=={'subject':None,'body':'Hello {{name}}','is_html':False,'expected_updated_at':None}
    assert seen[4][3]=={'expected_updated_at':'2026-10-16T12:01:00Z'}
    assert seen[5][0:2]==('POST','/api/leads/7/verify')

    assert seen[6][0:2]==('POST','/api/leads/7/unconfirmed-unsubscribes/9/review')
    assert seen[6][3]=={'decision':'rejected'}
