"""Official subscription OAuth only. Never reads or accepts an OpenAI API key."""
from contextlib import contextmanager
import base64
import fcntl
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import sys
import threading
import time
from urllib.parse import urlencode, urlsplit, parse_qs
import uuid

import httpx
import jwt

ROOT=Path.home()/'.openjarvis/chatgpt-subscription'
ISSUER='https://auth.openai.com'
TOKEN=ISSUER+'/api/accounts/oauth/token'
RESOURCE='https://api.openai.com/v1'
REQUIRED={'chatgpt.tokens.use.direct','resource.invoke'}
LOCK=threading.RLock()


def prepare():
    ROOT.mkdir(parents=True,exist_ok=True,mode=0o700)
    ROOT.chmod(0o700)
    (ROOT/'accounts').mkdir(exist_ok=True,mode=0o700)


def save(path,data):
    prepare()
    temporary=path.with_name(path.name+'.'+secrets.token_hex(6)+'.tmp')
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try:
        with os.fdopen(fd,'w') as file:json.dump(data,file)
        temporary.replace(path)
    finally:temporary.unlink(missing_ok=True)


def read(path,default=None):
    try:return json.loads(path.read_text())
    except FileNotFoundError:return default


def account_path(client_id):
    return ROOT/'accounts'/(hashlib.sha256(client_id.encode()).hexdigest()+'.json')


def registrations():
    prepare()
    records=[]
    for path in sorted((ROOT/'accounts').glob('*.json')):
        record=read(path,{})
        if record.get('client_id') and record.get('subject'):
            records.append({'client_id':record['client_id'],'email':record.get('email',''),
                            'label':record.get('email','ChatGPT')+' · '+record['client_id'][-8:]})
    return records


def active():
    record=read(ROOT/'active.json',{})
    client_id=record.get('client_id')
    return read(account_path(client_id)) if client_id else None


def verify_id(encoded,client_id,nonce=None,subject=None):
    key=jwt.PyJWKClient(ISSUER+'/.well-known/jwks.json',timeout=10).get_signing_key_from_jwt(encoded)
    claims=jwt.decode(encoded,key.key,algorithms=['RS256'],audience=client_id,issuer=ISSUER,
                      options={'require':['iss','aud','exp','sub']})
    if nonce is not None and not secrets.compare_digest(str(claims.get('nonce','')),nonce):
        raise ValueError('Sign-in nonce did not match. Start sign-in again.')
    if subject is not None and claims['sub']!=subject:
        raise ValueError('The signed-in account changed. Sign in again.')
    return claims


def checked_tokens(tokens,client_id,nonce=None,previous=None):
    scopes=set(str(tokens.get('scope','')).split()) if tokens.get('scope') is not None else set((previous or {}).get('scopes',[]))
    if not REQUIRED.issubset(scopes):raise ValueError('ChatGPT plan usage was not authorised. Sign in and enable plan usage.')
    if str(tokens.get('token_type','')).lower()!='bearer':raise ValueError('Unsupported sign-in token type.')
    if not tokens.get('access_token') or not tokens.get('refresh_token'):
        raise ValueError('Sign-in did not return renewable subscription credentials.')
    encoded=tokens.get('id_token')
    if encoded:
        claims=verify_id(encoded,client_id,nonce,(previous or {}).get('subject'))
    elif previous and nonce is None:
        claims={'sub':previous['subject'],'email':previous.get('email','')}
        encoded=previous['id_token']
    else:raise ValueError('Sign-in did not return a validated identity token.')
    return {'client_id':client_id,'issuer':ISSUER,'subject':claims['sub'],'email':claims.get('email',''),
            'access_token':tokens['access_token'],'refresh_token':tokens['refresh_token'],
            'id_token':encoded,'scopes':sorted(scopes),'expires_at':time.time()+int(tokens.get('expires_in',3600)),
            'earliest_refresh_at':tokens.get('earliest_refresh_at'),
            'plan_only_confirmed':bool((previous or {}).get('plan_only_confirmed',False)),
            'ext_agent_host_id':read(ROOT/'host.json')['ext_agent_host_id'],
            'connected_at':(previous or {}).get('connected_at',0)}


@contextmanager
def locked_account(client_id):
    prepare()
    with (account_path(client_id).with_suffix('.lock')).open('a') as lock:
        os.chmod(lock.name,0o600)
        fcntl.flock(lock,fcntl.LOCK_EX)
        yield


@contextmanager
def activation_lock():
    prepare()
    with (ROOT/'activation.lock').open('a') as lock:
        os.chmod(lock.name,0o600)
        fcntl.flock(lock,fcntl.LOCK_EX)
        yield


def access_token(require_plan_only=True):
    current=active()
    if not current:raise ValueError('Connect ChatGPT in Personal → ChatGPT subscription.')
    with locked_account(current['client_id']):
        current=read(account_path(current['client_id']))
        if require_plan_only and not current.get('plan_only_confirmed'):
            raise ValueError('Confirm credit spending is disabled for Jarvis in ChatGPT usage settings before using the subscription.')
        if not REQUIRED.issubset(set(current.get('scopes',[]))):raise ValueError('ChatGPT plan usage is not authorised.')
        if time.time()>=current['expires_at']-60:
            with httpx.Client(timeout=20,trust_env=False) as client:
                response=client.post(TOKEN,data={'grant_type':'refresh_token','client_id':current['client_id'],
                      'refresh_token':current['refresh_token'],'resource':RESOURCE})
            if response.status_code!=200:raise ValueError('ChatGPT sign-in expired or could not renew. Reconnect in Personal.')
            updated=checked_tokens(response.json(),current['client_id'],previous=current)
            save(account_path(current['client_id']),updated);current=updated
        return current['access_token']


def models():
    with activation_lock():
        return _models_locked()


def _models_locked():
    token=access_token(require_plan_only=False)
    with httpx.Client(timeout=15,trust_env=False) as client:
        response=client.get(RESOURCE+'/models',headers={'Authorization':'Bearer '+token})
    if response.status_code!=200:raise ValueError('ChatGPT subscription model access is unavailable for this account. Reconnect or review ChatGPT usage settings.')
    data=response.json()
    result=[{'id':'chatgpt-subscription/'+m['slug'],'slug':m['slug'],'name':m.get('display_name',m['slug'])}
            for m in data.get('models',[]) if m.get('visibility')=='list' and isinstance(m.get('slug'),str)]
    if not result:raise ValueError('No subscription models are available for this account.')
    save(ROOT/'models.json',{'models':result,'updated_at':time.time(),'client_id':active()['client_id']})
    return result


def status():
    current=active()
    pending=read(ROOT/'login-status.json',{})
    return {'connected':bool(current),'plan_only_confirmed':bool(current and current.get('plan_only_confirmed')),
            'billing':'ChatGPT subscription only; API-key billing disabled',
            'email':current.get('email','') if current else '',
            'client_label':(current or {}).get('client_id','')[-12:],
            'account_id':(current or {}).get('client_id',''),
            'session_id':(current or {}).get('connected_at',0),
            'login_state':pending.get('state','not_started'),'message':pending.get('message',''),
            'models':read(ROOT/'models.json',{}).get('models',[]) if current and read(ROOT/'models.json',{}).get('client_id')==current['client_id'] else [],
            'accounts':registrations(),
            'manage_usage_url':'https://chatgpt.com/settings/usage'}


def confirm_plan_only():
    current=active()
    if not current:raise ValueError('Sign in first.')
    with locked_account(current['client_id']):
        current=read(account_path(current['client_id']));current['plan_only_confirmed']=True
        save(account_path(current['client_id']),current)
    return status()


def disconnect():
    with activation_lock():
        return _disconnect_locked()


def _disconnect_locked():
    (ROOT/'login-pending.json').unlink(missing_ok=True)
    current=active();revoked=False
    if current:
        with locked_account(current['client_id']):
            current=read(account_path(current['client_id']))
            try:
                with httpx.Client(timeout=15,trust_env=False) as client:
                    response=client.post(ISSUER+'/api/accounts/oauth/revoke',data={'token':current['refresh_token'],
                        'token_type_hint':'refresh_token','client_id':current['client_id']})
                    revoked=response.status_code==200
            except httpx.HTTPError:pass
            # Retain the account/client identity mapping, but no reusable token.
            save(account_path(current['client_id']),{k:current[k] for k in ('client_id','subject','email','ext_agent_host_id')})
            (ROOT/'active.json').unlink(missing_ok=True)
            (ROOT/'models.json').unlink(missing_ok=True)
    return {'disconnected':True,'remote_revocation_confirmed':revoked,
            'message':'Disconnected.' if revoked else 'Local credentials cleared. Remote revocation was not confirmed; disconnect Jarvis in ChatGPT settings too.'}


def login(client_id=None,new_account=False):
    prepare()
    with (ROOT/'login.lock').open('a') as lock:
        os.chmod(lock.name,0o600)
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        host=read(ROOT/'host.json')
        if not host:
            host={'ext_agent_host_id':'urn:uuid:'+str(uuid.uuid4())};save(ROOT/'host.json',host)
        saved=registrations()
        if client_id:
            if client_id not in {r['client_id'] for r in saved}:raise ValueError('Unknown saved ChatGPT account.')
            selected=read(account_path(client_id))
        elif new_account:selected=None
        else:
            selected=active()
            if not selected and len(saved)==1:selected=read(account_path(saved[0]['client_id']))
        pending={'state':secrets.token_urlsafe(32),'nonce':secrets.token_urlsafe(32),'verifier':secrets.token_urlsafe(64)}
        finished=threading.Event()
        handoff=secrets.token_urlsafe(32)
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass  # Callback URLs contain single-use codes.
            def do_GET(self):
                if self.headers.get('Host')==f'127.0.0.1:{self.server.server_port}' and self.path=='/start/'+handoff:
                    self.send_response(302);self.send_header('Location',url);self.send_header('Cache-Control','no-store');self.end_headers();return
                if self.headers.get('Host')!=f'127.0.0.1:{self.server.server_port}' or urlsplit(self.path).path!='/auth/callback':
                    self.send_error(404);return
                query=parse_qs(urlsplit(self.path).query)
                state=query.get('state',[''])[0]
                if not secrets.compare_digest(state,pending['state']):self.send_error(400,'Invalid sign-in state');return
                message='Sign-in did not complete. Start sign-in again from Jarvis.'
                try:
                    if query.get('error'):raise ValueError('ChatGPT sign-in was declined or unavailable. No connection was activated.')
                    if read(ROOT/'login-pending.json',{}).get('attempt')!=pending['state']:raise ValueError('This sign-in was cancelled. Start again.')
                    code=query.get('code',[''])[0]
                    client_id=query.get('client_id',[selected['client_id'] if selected else ''])[0]
                    if not code or not client_id or client_id=='dynamic_agent_client':raise ValueError('Registration did not return an issued client ID.')
                    if selected and client_id!=selected['client_id']:raise ValueError('The sign-in registration changed unexpectedly.')
                    with httpx.Client(timeout=20,trust_env=False) as client:
                        response=client.post(TOKEN,data={'grant_type':'authorization_code','client_id':client_id,'code':code,
                            'code_verifier':pending['verifier'],'redirect_uri':redirect,'resource':RESOURCE})
                    if response.status_code!=200:raise ValueError('The sign-in code could not be exchanged. Start sign-in again.')
                    current=checked_tokens(response.json(),client_id,pending['nonce'],selected)
                    # New consent always requires confirmation that credit usage is off.
                    current['plan_only_confirmed']=False
                    current['connected_at']=time.time()
                    with activation_lock(), locked_account(client_id):
                        if read(ROOT/'login-pending.json',{}).get('attempt')!=pending['state']:raise ValueError('This sign-in was cancelled. Start again.')
                        save(account_path(client_id),current);save(ROOT/'active.json',{'client_id':client_id})
                    models()
                    message='Signed in to Jarvis. In ChatGPT Usage settings, disable credit spending for Jarvis, then confirm subscription-only use in Jarvis Personal. No model request has been sent.'
                    save(ROOT/'login-status.json',{'state':'connected','message':message})
                except Exception as error:
                    safe=str(error) if isinstance(error,ValueError) else 'Secure sign-in validation failed. Please reconnect; no API-key fallback was used.'
                    message=safe;save(ROOT/'login-status.json',{'state':'error','message':safe})
                self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8')
                self.send_header('Cache-Control','no-store');self.send_header('Content-Security-Policy',"default-src 'none'; style-src 'unsafe-inline'")
                self.end_headers()
                import html
                self.wfile.write(('<html><title>Jarvis sign-in</title><body style="background:#071019;color:#dbeaf3;font:18px system-ui;padding:12vh 10vw"><h1>Jarvis</h1><p>'+html.escape(message)+'</p><p>You can close this tab and return to Jarvis.</p></body></html>').encode())
                finished.set()
        with ThreadingHTTPServer(('127.0.0.1',0),Handler) as server:
            server.timeout=1
            redirect=f'http://127.0.0.1:{server.server_port}/auth/callback'
            params={'client_id':selected['client_id'] if selected else 'dynamic_agent_client',
                    'ext_agent_host_id':host['ext_agent_host_id'],'response_type':'code','redirect_uri':redirect,
                    'scope':'openid profile email offline_access resource.invoke chatgpt.tokens.use.direct',
                    'resource':RESOURCE,'state':pending['state'],'nonce':pending['nonce'],'code_challenge_method':'S256',
                    'code_challenge':base64.urlsafe_b64encode(hashlib.sha256(pending['verifier'].encode()).digest()).decode().rstrip('=')}
            if selected and selected.get('id_token'):
                params['id_token_hint']=selected['id_token']
            if not selected:params['agent_name_hint']='Jarvis'
            url=ISSUER+'/api/accounts/authorize?'+urlencode(params)
            # Protected, short-lived handoff. Never print tokens or authorization URLs.
            save(ROOT/'login-pending.json',{'url':url,'handoff_url':f'http://127.0.0.1:{server.server_port}/start/'+handoff,'expires_at':time.time()+900,'attempt':pending['state']})
            save(ROOT/'login-status.json',{'state':'waiting','message':'Complete ChatGPT sign-in in your browser.'})
            deadline=time.monotonic()+900
            while not finished.is_set() and time.monotonic()<deadline:server.handle_request()
            if not finished.is_set():save(ROOT/'login-status.json',{'state':'expired','message':'Sign-in timed out. Start again.'})
            (ROOT/'login-pending.json').unlink(missing_ok=True)


if __name__=='__main__':
    if '--login' in sys.argv:
        selected_id=sys.argv[sys.argv.index('--account')+1] if '--account' in sys.argv else None
        login(selected_id,'--new-account' in sys.argv)
    else:print(json.dumps(status(),indent=2))
