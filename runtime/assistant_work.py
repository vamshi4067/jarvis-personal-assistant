"""Durable user goals and a shared view over existing Jarvis work, without another executor."""
from datetime import datetime,timezone
from pathlib import Path
import json
import os
import re
import sqlite3
from uuid import uuid4

service=None

def now():return datetime.now(timezone.utc).isoformat()
def clean(value,limit):
    if not isinstance(value,str) or not value.strip() or len(value)>limit:raise ValueError('Enter nonempty text within the field limit.')
    return value.strip()

class WorkStore:
    def __init__(self,path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS goals(id TEXT PRIMARY KEY,title TEXT NOT NULL,state TEXT NOT NULL,notes TEXT NOT NULL,due TEXT,created TEXT,updated TEXT);
            CREATE TABLE IF NOT EXISTS steps(id TEXT PRIMARY KEY,goal_id TEXT NOT NULL REFERENCES goals(id),text TEXT NOT NULL,state TEXT NOT NULL,report_id TEXT,created TEXT);
            CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY,label TEXT NOT NULL,goal_id TEXT,created TEXT);''')
        os.chmod(self.path,0o600)
    def connect(self):
        db=sqlite3.connect(self.path,timeout=20);db.row_factory=sqlite3.Row;db.execute('PRAGMA foreign_keys=ON');return db
    def event(self,db,label,goal=None):db.execute('INSERT INTO events VALUES(?,?,?,?)',(uuid4().hex,label,goal,now()))
    def goal(self,id):
        with self.connect() as db:
            row=db.execute('SELECT * FROM goals WHERE id=?',(id,)).fetchone()
            if not row:raise ValueError('Goal not found.')
            result=dict(row);result['steps']=[dict(r) for r in db.execute('SELECT * FROM steps WHERE goal_id=? ORDER BY created',(id,))];return result
    def goals(self):
        with self.connect() as db:ids=[r['id'] for r in db.execute('SELECT id FROM goals ORDER BY updated DESC LIMIT 100')]
        return [self.goal(id) for id in ids]
    def create_goal(self,title,notes='',due=None):
        title=clean(title,200)
        if not isinstance(notes,str) or len(notes)>4000:raise ValueError('Use at most 4000 characters for notes.')
        if due:
            try:datetime.fromisoformat(due)
            except (ValueError,TypeError):raise ValueError('Use an ISO date for the target date.')
        id=uuid4().hex;t=now()
        with self.connect() as db:
            db.execute('INSERT INTO goals VALUES(?,?,?,?,?,?,?)',(id,title,'planned',notes,due,t,t));self.event(db,'Created goal: '+title,id)
        return self.goal(id)
    def update_goal(self,id,state=None,title=None,notes=None):
        goal=self.goal(id)
        if state is not None:
            if state not in ('planned','active','paused','completed'):raise ValueError('Choose planned, active, paused or completed.')
            goal['state']=state
        if title is not None:goal['title']=clean(title,200)
        if notes is not None:
            if not isinstance(notes,str) or len(notes)>4000:raise ValueError('Use at most 4000 characters for notes.')
            goal['notes']=notes
        with self.connect() as db:
            db.execute('UPDATE goals SET state=?,title=?,notes=?,updated=? WHERE id=?',(goal['state'],goal['title'],goal['notes'],now(),id));self.event(db,'Updated goal: '+goal['title'],id)
        return self.goal(id)
    def add_step(self,goal_id,text):
        self.goal(goal_id);text=clean(text,1500);id=uuid4().hex
        with self.connect() as db:
            if db.execute('SELECT COUNT(*) FROM steps WHERE goal_id=?',(goal_id,)).fetchone()[0]>=50:raise ValueError('A goal can have at most 50 steps.')
            db.execute('INSERT INTO steps VALUES(?,?,?,?,?,?)',(id,goal_id,text,'pending',None,now()));db.execute('UPDATE goals SET updated=? WHERE id=?',(now(),goal_id));self.event(db,'Added goal step',goal_id)
        return self.goal(goal_id)
    def update_step(self,id,state=None,report_id=None):
        if state is not None and state not in ('pending','done'):raise ValueError('Choose pending or done.')
        if report_id is not None and not re.fullmatch(r'[a-f0-9]{32}',report_id):raise ValueError('Invalid report ID.')
        with self.connect() as db:
            row=db.execute('SELECT * FROM steps WHERE id=?',(id,)).fetchone()
            if not row:raise ValueError('Step not found.')
            db.execute('UPDATE steps SET state=?,report_id=? WHERE id=?',(state or row['state'],report_id or row['report_id'],id));db.execute('UPDATE goals SET updated=? WHERE id=?',(now(),row['goal_id']));self.event(db,'Updated goal step',row['goal_id'])
        return self.goal(row['goal_id'])
    def activity(self):
        with self.connect() as db:return [dict(r) for r in db.execute('SELECT * FROM events ORDER BY created DESC LIMIT 50')]

class AssistantWork:
    def __init__(self,app,store):self.app=app;self.store=store
    def status(self):
        reports=self.app.state.reports.list_reports()
        manager=getattr(self.app.state,'agent_manager',None)
        agents=manager.list_agents() if manager else []
        agents=[{'id':a['id'],'name':a.get('name','Managed task'),'status':a.get('status'),
                 'schedule_type':a.get('config',{}).get('schedule_type','manual'),'schedule_value':a.get('config',{}).get('schedule_value')} for a in agents]
        personal=self.app.state.personal_store.actions()[:30]
        activity=self.store.activity()+[{'id':a['id'],'label':a['label'],'created':a['created']} for a in personal]
        for r in reports[:30]:activity.append({'id':'report-'+r['id'],'label':r['title']+' — '+r['status'],'created':r.get('updated',r['created'])})
        activity.sort(key=lambda e:e['created'],reverse=True)
        return {'goals':self.store.goals(),'reports':reports,'agents':agents,'activity':activity[:60]}
    def action(self,action,**p):
        if action=='create_goal':return self.store.create_goal(p.get('title'),p.get('notes',''),p.get('due'))
        if action=='update_goal':return self.store.update_goal(p.get('goal_id'),p.get('state'),p.get('title'),p.get('notes'))
        if action=='add_step':return self.store.add_step(p.get('goal_id'),p.get('text'))
        if action=='update_step':return self.store.update_step(p.get('step_id'),p.get('state'))
        if action=='link_report':
            self.app.state.reports.get(p.get('report_id',''))
            return self.store.update_step(p.get('step_id'),report_id=p.get('report_id'))
        if action=='start_report':
            # Validate the step before starting any work.
            step=p.get('step_id');found=None
            if step:
                with self.store.connect() as db:found=db.execute('SELECT * FROM steps WHERE id=?',(step,)).fetchone()
                if not found:raise ValueError('Step not found.')
            report=self.app.state.reports.start(clean(p.get('topic'),1000))
            if found:self.store.update_step(step,report_id=report['id'])
            return report
        if action in ('pause_agent','resume_agent'):
            manager=getattr(self.app.state,'agent_manager',None);id=p.get('agent_id')
            if not manager or not manager.get_agent(id):raise ValueError('Managed task not found.')
            if action=='pause_agent':manager.pause_agent(id)
            else:manager.resume_agent(id)
            return {'agent_id':id,'future_runs':'paused' if action=='pause_agent' else 'enabled','current_run_cancelled':False}
        if action=='status':
            data=self.status()
            return {'goals':[{'id':g['id'],'title':g['title'],'state':g['state'],'steps':[{'id':s['id'],'text':s['text'][:180],'state':s['state'],'report_id':s['report_id']} for s in g['steps'][:4]],'total_steps':len(g['steps'])} for g in data['goals'][:4]],
                    'reports':[{k:r.get(k) for k in ('id','title','status','source_count')} for r in data['reports'][:6]],
                    'agents':data['agents'][:6],'total_goals':len(data['goals']),'total_reports':len(data['reports']),
                    'more':'Open Personal → My goals and work for the full inbox.'}
        raise ValueError('Unknown work action.')


def register_work_tool():
    from openjarvis.core.registry import ToolRegistry
    from openjarvis.core.types import ToolResult
    from openjarvis.tools._stubs import BaseTool,ToolSpec
    if 'assistant_work' in ToolRegistry.keys():return
    @ToolRegistry.register('assistant_work')
    class AssistantWorkTool(BaseTool):
        tool_id='assistant_work';is_local=True
        @property
        def spec(self):
            return ToolSpec(name=self.tool_id,category='productivity',timeout_seconds=15,
                description='Maintain user goals and steps, inspect real work/results, and start a cited PDF/Word report linked to a step. A plan request creates a goal and steps, not background actions. Mark steps done only from actual completion or user confirmation. Goal state does not alter independent schedules. Pause/resume only the specific managed task the user names; pausing future runs does not cancel an active run. Do not repeatedly poll or invent completion.',
                parameters={'type':'object','properties':{'action':{'type':'string','enum':['create_goal','update_goal','add_step','update_step','link_report','start_report','pause_agent','resume_agent','status']},**{k:{'type':'string'} for k in ('title','notes','due','goal_id','step_id','state','text','report_id','topic','agent_id')}},'required':['action']})
        def execute(self,**params):
            if service is None:return ToolResult(tool_name=self.tool_id,success=False,content='Work service is not ready.')
            try:
                p=dict(params);action=p.pop('action',None)
                return ToolResult(tool_name=self.tool_id,success=True,content=json.dumps(service.action(action,**p)))
            except (ValueError,KeyError,TypeError) as error:return ToolResult(tool_name=self.tool_id,success=False,content=str(error))


def install_work(app):
    from fastapi import APIRouter,Depends,HTTPException,Request
    from pydantic import BaseModel,Field
    from urllib.parse import urlsplit
    global service
    service=AssistantWork(app,WorkStore(Path.home()/'.openjarvis/assistant-work.db'))
    app.state.assistant_work=service
    def guard(request:Request):
        origin=request.headers.get('origin')
        if origin and urlsplit(origin).netloc!=request.headers.get('host'):raise HTTPException(403,'Use your Jarvis page.')
        if request.method=='POST' and request.headers.get('x-jarvis-personal')!='1':raise HTTPException(403,'Use Jarvis controls.')
    router=APIRouter(prefix='/v1/personal/work',dependencies=[Depends(guard)])
    @router.get('')
    def status():return service.status()
    @router.post('')
    async def change(request:Request):
        try:
            raw=await request.body()
            if len(raw)>12000:raise ValueError('The request is too large.')
            body=json.loads(raw)
            if not isinstance(body,dict):raise ValueError('Use a work action object.')
            action=body.pop('action',None)
            return service.action(action,**body)
        except (ValueError,KeyError,TypeError) as error:raise HTTPException(400,str(error))
    before=len(app.router.routes);app.include_router(router)
    app.router.routes[:]=app.router.routes[before:]+app.router.routes[:before]
