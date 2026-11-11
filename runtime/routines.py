"""Local routines with explicit, limited steps."""
import json
import re
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

ROOT = Path.home() / '.openjarvis'
FILE = ROOT / 'routines.json'
LOCK = threading.Lock()
STARTER = {'start work': {'sites': [], 'reminders': True}}
ZONE = ZoneInfo('America/New_York')

class Routine(BaseModel):
    phrase: str = Field(min_length=1, max_length=60)
    sites: list[str] = Field(default_factory=list, max_length=8)
    reminders: bool = True

def key(text):
    return ' '.join(text.strip().rstrip('.!?').lower().split())

def load():
    return json.loads(FILE.read_text()) if FILE.exists() else dict(STARTER)

def save(data, destination=FILE):
    import tempfile
    import os
    with tempfile.NamedTemporaryFile(mode='w', dir=ROOT, delete=False) as out:
        name = out.name
        json.dump(data, out)
    try: os.replace(name, destination)
    finally: Path(name).unlink(missing_ok=True)

def valid_url(url):
    if len(url)>2048 or any(c.isspace() or ord(c)<32 for c in url):return False
    try:
        p=urlsplit(url)
        return p.scheme=='https' and bool(p.hostname) and not (p.username or p.password)
    except ValueError:return False

HANDOFF = ROOT / 'work-handoff.json'

class Handoff(BaseModel):
    sites: list[str] = Field(default_factory=list, max_length=8)
    files: list[str] = Field(default_factory=list, max_length=8)
    next_step: str = Field(default='', max_length=2000)

def document(value):
    p = Path(value).expanduser().resolve(strict=True)
    if not p.is_relative_to(Path.home().resolve()) or not p.is_file() or p.suffix.lower() not in {'.md','.txt','.pdf','.docx','.xlsx','.pptx','.csv','.png','.jpg','.jpeg'}:
        raise ValueError('Choose an existing document in your home folder.')
    return p

def restore():
    with LOCK:
        data=json.loads(HANDOFF.read_text()) if HANDOFF.exists() else None
    if not data:return 'No work handoff saved. Add one on the Routines page.'
    lines=[]
    for kind in ('sites','files'):
        for value in data[kind]:
            try:
                target=value if kind=='sites' and valid_url(value) else str(document(value)) if kind=='files' else None
                if not target:raise ValueError()
                label=urlsplit(target).hostname if kind=='sites' else Path(target).name
                result=subprocess.run(['/usr/bin/open',target],capture_output=True,timeout=5)
                lines.append(('Mac accepted the open request: ' if result.returncode==0 else 'Could not open: ')+label)
            except (ValueError,OSError,RuntimeError,subprocess.TimeoutExpired):
                lines.append('Could not open one saved '+('site.' if kind=='sites' else 'document.'))
    if data['next_step']:lines.append("Next step: "+data['next_step'])
    return '\n'.join(lines) or 'The saved handoff is empty.'

def run(phrase, store=None):
    if key(phrase) in {'pick up where i left off','resume my work'}:return restore()
    if key(phrase) in {"i’m done for today","i'm done for today","i am done for today"}:
        return 'Open [Routines](/personal/routines) and save the websites, documents and next step you want to resume.'
    with LOCK: routine=load().get(key(phrase))
    if routine is None:return None
    lines=[]
    for url in routine['sites']:
        if not valid_url(url):
            lines.append('Skipped an invalid website.');continue
        host=urlsplit(url).hostname
        try:
            result=subprocess.run(['/usr/bin/open',url],capture_output=True,timeout=8)
            lines.append(f'Mac accepted the request to open {host}.' if result.returncode==0 else f'Could not open {host}.')
        except (OSError,subprocess.TimeoutExpired):lines.append(f'Could not confirm opening {host}.')
    if routine['reminders']:
        try:
            if store is None:
                from personal_store import PersonalStore
                store=PersonalStore(ROOT/'personal.db')
            today=datetime.now(ZONE).date()
            rows=[item for item in store.reminders() if item['status']!='dismissed'
                  and datetime.fromisoformat(item['due']).astimezone(ZONE).date()==today]
            lines.append('Today’s reminders:')
            lines.extend(f"- {datetime.fromisoformat(item['due']).astimezone(ZONE):%I:%M %p}: {item['text']}" for item in rows[:15])
            if not rows:lines.append('No reminders are scheduled for today.')
            if len(rows)>15:lines.append(f'{len(rows)-15} more are in Personal → Reminders.')
        except Exception:lines.append('Could not read today’s reminders.')
    return 'Routine: '+key(phrase)+'\n\n'+'\n'.join(lines)

def install(app):
    router=APIRouter()
    def guard(request, write=False):
        host=request.headers.get('host','')
        if host not in ('localhost:18766','127.0.0.1:18766'):raise HTTPException(403)
        if write and (request.headers.get('x-jarvis-routine')!='1' or request.headers.get('origin')!=f'http://{host}'):
            raise HTTPException(403)
    @router.get('/v1/personal/handoff')
    def handoff(request:Request):
        guard(request)
        with LOCK:return json.loads(HANDOFF.read_text()) if HANDOFF.exists() else {}
    @router.put('/v1/personal/handoff')
    def update_handoff(body:Handoff,request:Request):
        guard(request,True)
        if any(not valid_url(u) for u in body.sites):raise HTTPException(400,'Use HTTPS addresses.')
        try: files=[str(document(p)) for p in body.files]
        except (ValueError,OSError,RuntimeError):raise HTTPException(400,'Use full paths to existing documents in your home folder.')
        with LOCK:save(dict(sites=body.sites,files=files,next_step=body.next_step.strip()),HANDOFF)
        return {'saved':True}
    @router.post('/v1/personal/handoff/restore')
    def restore_handoff(request:Request):
        guard(request,True)
        return {'result':restore()}
    teaching = {'active':False,'urls':[],'listeners':[]}
    def detach():
        teaching['active']=False
        for emitter,event,callback in teaching['listeners']:
            try:emitter.remove_listener(event,callback)
            except Exception:pass
        teaching['listeners'].clear()
    @router.post('/v1/personal/teach/{action}')
    def teach(action:str,request:Request):
        guard(request,True)
        if action not in ('start','status','stop','cancel'):raise HTTPException(404)
        from openjarvis.tools import browser
        owner=browser._jarvis_owner
        session=browser._session
        def step():
            if action=='start':
                if teaching['active']:return {'active':True,'sites':list(teaching['urls'])}
                session._ensure_browser()
                teaching['urls']=[]
                teaching['expires']=__import__('time').monotonic()+600
                teaching['active']=True
                def attach(page):
                    def navigated(frame):
                        if not teaching['active'] or __import__('time').monotonic()>teaching['expires'] or frame!=page.main_frame:return
                        url=frame.url
                        # Query strings and fragments can carry credentials or identifiers.
                        if not valid_url(url):return
                        parts=urlsplit(url)
                        clean=parts._replace(query='',fragment='').geturl()
                        if re.search(r'/(?:login|signin|sign-in|oauth|auth|checkout|payment|reset)(?:/|$)',parts.path,re.I):return
                        if clean not in teaching['urls'] and len(teaching['urls'])<8:teaching['urls'].append(clean)
                    page.on('framenavigated',navigated)
                    teaching['listeners'].append((page,'framenavigated',navigated))
                context=session._browser
                for page in context.pages:attach(page)
                context.on('page',attach)
                teaching['listeners'].append((context,'page',attach))
            elif teaching['active']:
                # A Playwright round trip delivers queued navigation events.
                for page in session._browser.pages:
                    if not page.is_closed():
                        page.title()
                        break
                if action in ('stop','cancel') or __import__('time').monotonic()>teaching['expires']:detach()
            if action=='cancel':teaching['urls']=[]
            return {'active':teaching['active'],'sites':list(teaching['urls'])}
        try:return owner.call(step)
        except Exception:raise HTTPException(503,'Jarvis’s browser is unavailable. Try again shortly.')
    @router.get('/personal/routines',response_class=HTMLResponse)
    def page(request:Request):
        guard(request)
        return Path(__file__).with_name('routines.html').read_text()
    @router.get('/personal/routines.js')
    def script(request:Request):
        guard(request)
        return Response(Path(__file__).with_name('routines.js').read_text(),media_type='application/javascript')
    @router.get('/v1/personal/routines')
    def listing(request:Request):
        guard(request)
        with LOCK:return load()
    @router.put('/v1/personal/routines')
    def update(body:Routine,request:Request):
        guard(request,True)
        phrase=key(body.phrase)
        if not re.fullmatch(r'[a-z0-9][a-z0-9 -]{0,59}',phrase) or phrase in {'wake up','good morning','stop','wait','stop talking','stop speaking','be quiet'} or phrase.startswith(('hey jarvis','read my','play my','tell me my')):
            raise HTTPException(400,'Choose a distinct phrase using letters, numbers and spaces.')
        if any(not valid_url(url) for url in body.sites):raise HTTPException(400,'Use full HTTPS website addresses.')
        if not body.sites and not body.reminders:raise HTTPException(400,'Add at least one step.')
        with LOCK:
            data=load()
            if phrase not in data and len(data)>=50:raise HTTPException(400,'Remove an existing routine first.')
            data[phrase]={'sites':body.sites,'reminders':body.reminders};save(data)
        return {'saved':phrase}
    @router.delete('/v1/personal/routines/{phrase}')
    def remove(phrase:str,request:Request):
        guard(request,True)
        with LOCK:
            data=load()
            if data.pop(key(phrase),None) is None:raise HTTPException(404)
            save(data)
        return {'removed':phrase}
    @router.post('/v1/personal/routines/{phrase}/run')
    def execute(phrase:str,request:Request):
        guard(request,True)
        result=run(phrase,app.state.personal_store)
        if result is None:raise HTTPException(404)
        return {'result':result}
    before=len(app.router.routes)
    app.include_router(router)
    app.router.routes[:]=app.router.routes[before:]+app.router.routes[:before]
