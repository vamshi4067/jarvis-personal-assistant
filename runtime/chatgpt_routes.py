"""Local account controls. No API key, credential disclosure, or inference probes."""
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlsplit
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
import chatgpt_subscription as subscription
from chatgpt_engine import PREFIX

class LoginBody(BaseModel):
    account: str = ''
    new_account: bool = False

class ConfirmBody(BaseModel):
    credits_disabled: bool = False
    model: str = ''
    account_id: str = ''
    session_id: float = 0


def activate(app,model):
    available={m['id'] for m in subscription.status()['models']}
    if model not in available:raise ValueError('Choose a model from your account catalog.')
    # Persist the no-fallback policy before changing any legacy defaults.
    subscription.save(subscription.ROOT/'policy.json',{'enabled':True,'model':model})
    import tomlkit
    path=Path.home()/'.openjarvis/openjarvis-personal.toml'
    document=tomlkit.parse(path.read_text())
    document.setdefault('intelligence',{})['default_model']=model
    document['intelligence']['preferred_engine']='chatgpt-subscription'
    document.setdefault('server',{})['model']=model
    path.write_text(tomlkit.dumps(document))
    app.state.model=model
    config=getattr(app.state,'config',None)
    if config:
        config.intelligence.default_model=model
        config.intelligence.preferred_engine='chatgpt-subscription'
        config.server.model=model
    return {'active':True,'model':model,'message':'Using your ChatGPT plan only. No paid API or alternate provider fallback.'}


def install_chatgpt(app):
    def guard(request:Request):
        host=request.headers.get('host','')
        if urlsplit('http://'+host).hostname not in ('127.0.0.1','localhost','::1'):
            raise HTTPException(403,'Account settings are available only on this Mac.')
        if request.headers.get('x-jarvis-personal')!='1':raise HTTPException(403,'Use Jarvis Personal account settings.')
        origin=request.headers.get('origin')
        if origin and urlsplit(origin).netloc!=host:raise HTTPException(403,'Cross-origin account changes are not allowed.')
    router=APIRouter(prefix='/v1/personal/chatgpt',dependencies=[Depends(guard)])
    @router.get('/status')
    def status():return subscription.status()
    @router.post('/start')
    def start(body:LoginBody):
        subscription.prepare()
        args=[sys.executable,str(Path(__file__).with_name('chatgpt_subscription.py')),'--login']
        if body.account:args+=['--account',body.account]
        if body.new_account:args+=['--new-account']
        with (subscription.ROOT/'login.log').open('a') as log:
            (subscription.ROOT/'login.log').chmod(0o600)
            subprocess.Popen(args,stdout=log,stderr=log,stdin=subprocess.DEVNULL,start_new_session=True)
        for _ in range(40):
            pending=subscription.read(subscription.ROOT/'login-pending.json',{})
            if pending.get('expires_at',0)>time.time():return {'url':pending['handoff_url']}
            time.sleep(.1)
        raise HTTPException(503,'Sign-in could not start. Please try again.')
    @router.post('/models')
    def models():
        try:return {'models':subscription.models()}
        except Exception:raise HTTPException(409,'Could not refresh your account model catalog. Reconnect or review ChatGPT Usage settings.') from None
    @router.post('/confirm')
    def confirm(body:ConfirmBody):
        if not body.credits_disabled:raise HTTPException(400,'Disable Jarvis credit spending in ChatGPT Usage settings and confirm that here first.')
        try:
            with subscription.activation_lock():
                state=subscription.status()
                if body.account_id!=state['account_id'] or body.session_id!=state['session_id']:
                    raise ValueError('The signed-in account changed. Review its credit settings and confirm again.')
                available=state['models']
                chosen=body.model or (available[0]['id'] if available else '')
                if chosen not in {m['id'] for m in available}:raise ValueError('Refresh the account model catalog and choose a model first.')
                subscription.confirm_plan_only()
                return activate(app,chosen)
        except ValueError as error:raise HTTPException(409,str(error)) from None
    @router.post('/disconnect')
    def disconnect():return subscription.disconnect() # Keep no-fallback policy; reconnect is required.
    before=len(app.router.routes)
    app.include_router(router)
    app.router.routes[:]=app.router.routes[before:]+app.router.routes[:before]
