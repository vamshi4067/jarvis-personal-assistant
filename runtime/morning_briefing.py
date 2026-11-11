"""Read today's completed managed-agent report, fetching it only if missing."""
from datetime import datetime
from zoneinfo import ZoneInfo
import httpx
from fastapi import HTTPException,Request

TZ=ZoneInfo('America/New_York')
AGENT_NAME='Daily morning briefing'

def briefing_snapshot(manager,now=None):
    now=now or datetime.now(TZ)
    agents=[a for a in manager.list_agents() if a.get('name','').strip().casefold()==AGENT_NAME.casefold() and a.get('status')!='archived']
    if not agents:return {'status':'missing','text':'','message':'The Daily morning briefing agent was not found.'}
    agent=agents[0]
    messages=manager.list_messages(agent['id'],limit=100)
    for message in sorted(messages,key=lambda m:float(m.get('created_at') or 0),reverse=True):
        text=(message.get('content') or '').strip()
        if message.get('direction')!='agent_to_user' or not text or text.lower().startswith(('error:','maximum turns reached')):
            continue
        created=datetime.fromtimestamp(float(message.get('created_at')or 0),TZ)
        if created.date()==now.date():
            return {'status':'ready','agent_id':agent['id'],'agent_name':agent['name'],
                    'text':text,'created_at':created.isoformat(),'report_date':created.date().isoformat()}
    status='fetching' if agent.get('status')=='running' else 'paused' if agent.get('status')=='paused' else 'stale'
    return {'status':status,'agent_id':agent['id'],'agent_name':agent['name'],'text':''}

def add_morning_routes(router):
    def snapshot(request):
        manager=getattr(request.app.state,'agent_manager',None)
        if manager is None:raise HTTPException(503,'The scheduled-agent manager is unavailable')
        return briefing_snapshot(manager)

    @router.get('/morning-briefing')
    def morning_status(request:Request):return snapshot(request)

    @router.post('/morning-briefing')
    async def morning_fetch(request:Request):
        result=snapshot(request)
        if result['status'] in {'ready','fetching'}:return result
        if result['status']=='missing':raise HTTPException(404,result['message'])
        if result['status']=='paused':raise HTTPException(409,'Your morning briefing agent is paused. Resume it in Agents before asking for a new briefing.')
        # Reuse the native executor, including its lock against duplicate runs.
        headers={}
        if request.headers.get('authorization'):headers['authorization']=request.headers['authorization']
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=request.app),base_url='http://jarvis.internal',timeout=30) as client:
            response=await client.post('/v1/managed-agents/'+result['agent_id']+'/run',headers=headers)
        if response.status_code not in {200,409}:
            raise HTTPException(503,'Jarvis could not start the morning briefing. Check the agent’s status in Agents.')
        result['status']='fetching'
        return result
