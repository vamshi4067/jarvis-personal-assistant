"""Private Slack Socket Mode bridge to the configured local Jarvis web API."""
import json, logging, time, re, fcntl, os, sys, threading, subprocess, tomllib
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from collections import OrderedDict
import httpx

BASE = Path.home()/'.openjarvis'
STATUS_LOCK=threading.RLock()
CREDENTIALS = BASE / 'slack-bot.json'
STATUS = BASE / 'slack-bot-status.json'

def allowed_message(event, owner, bot):
 if not owner or event.get('user') != owner or event.get('user') == bot: return False
 if event.get('bot_id') or event.get('subtype') or not event.get('text','').strip(): return False
 return event.get('type') == 'app_mention' or (event.get('type') == 'message' and (event.get('channel_type') == 'im' or str(event.get('channel','')).startswith('D')))

def conversation_key(event):
 return event.get('channel',''), event.get('thread_ts','')

def set_status(state=None, **extra):
 with STATUS_LOCK:
  try: previous=json.loads(STATUS.read_text()) if STATUS.exists() else {}
  except (ValueError,OSError):previous={}
  if state is not None:previous['state']=state
  previous.update(updated_at=time.time(),**extra)
  temporary=STATUS.with_suffix('.tmp')
  fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
  with os.fdopen(fd,'w') as file:json.dump(previous,file)
  temporary.replace(STATUS)

def backend_settings():
 # Never inherit another Jarvis instance's port/model or cache an old provider.
 with (BASE/'openjarvis-personal.toml').open('rb') as file:cfg=tomllib.load(file)
 server=cfg.get('server',{});intelligence=cfg.get('intelligence',{})
 return f"http://127.0.0.1:{int(server.get('port',18766))}",server.get('model') or intelligence.get('default_model')

def ensure_worker():
 runtime=BASE/'runtime'
 with (runtime/'slack-bot.log').open('a') as log:
  subprocess.Popen([sys.executable,str(runtime/'slack_bridge.py')],cwd=runtime,
   stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)

def main():
 from slack_sdk import WebClient
 from slack_sdk.socket_mode import SocketModeClient
 from slack_sdk.socket_mode.response import SocketModeResponse
 lock = open(BASE / 'slack-bot.lock','a')
 try: fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
 except BlockingIOError: return
 if not CREDENTIALS.exists(): return
 cfg=json.loads(CREDENTIALS.read_text())
 bot=WebClient(token=cfg['bot_token'])
 auth=bot.auth_test()
 owner, bot_user=cfg['owner_user_id'],auth['user_id']
 base,model=backend_settings()
 set_status('starting',backend_port=int(base.rsplit(':',1)[1]),model=model,pid=os.getpid(),last_event_at=None,last_message_at=None,last_reply_at=None,error=None)
 histories={}; seen=OrderedDict()
 pool=ThreadPoolExecutor(max_workers=1)
 client=SocketModeClient(app_token=cfg['app_token'],web_client=bot)
 def reply(event):
  key=conversation_key(event)
  text=re.sub(r'<@'+re.escape(bot_user)+r'>','',event['text']).strip()
  messages=histories.get(key,[])+[{'role':'user','content':text}]
  thread=event.get('thread_ts') or (event.get('ts') if event.get('type')=='app_mention' else None)
  try:
   base,model=backend_settings()
   set_status('processing',backend_port=int(base.rsplit(':',1)[1]),model=model)
   with httpx.Client(trust_env=False,timeout=600) as http:
    response=http.post(base+'/v1/chat/completions',json={'model':model,'messages':messages,'stream':False,'max_tokens':4096})
    response.raise_for_status()
    answer=response.json()['choices'][0]['message']['content'] or 'Please try that request again.'
   histories[key]=(messages+[{'role':'assistant','content':answer}])[-20:]
   from openjarvis.channels.slack_daemon import _to_slack_fmt
   answer=_to_slack_fmt(answer)
   for start in range(0,len(answer),3000):
    bot.chat_postMessage(channel=event['channel'],text=answer[start:start+3000],**({'thread_ts':thread} if thread else {}))
   set_status('connected',last_reply_at=time.time())
  except Exception as exc:
   logging.error('Reply failed: %s',type(exc).__name__)
   set_status('reply_error',error=type(exc).__name__)
   bot.chat_postMessage(channel=event['channel'],text='Jarvis could not finish that request. Please check that its local web chat is running and try again.',**({'thread_ts':thread} if thread else {}))
 def receive(socket, req):
  # Acknowledge before inference so Slack does not retry a slow request.
  socket.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))
  if req.type != 'events_api':return
  event=req.payload.get('event',{})
  set_status(last_event_at=time.time(),last_event_type=event.get('type','unknown'))
  if not allowed_message(event,owner,bot_user):return
  event_id=req.payload.get('event_id',event.get('ts',''))
  if event_id in seen:return
  seen[event_id]=True
  if len(seen)>2000:seen.popitem(last=False)
  set_status('processing',last_message_at=time.time())
  pool.submit(reply,event)
 client.socket_mode_request_listeners.append(receive)
 set_status('connecting')
 try:
  client.connect()
  set_status('connected',socket_connected=client.is_connected())
  while True:
   set_status(socket_connected=client.is_connected(),heartbeat_at=time.time())
   time.sleep(5)
 finally:
  client.close();pool.shutdown(wait=False)

if __name__=='__main__':
 logging.basicConfig(level=logging.WARNING)
 while True:
  try:
   main()
   break # Another singleton worker already owns the connection.
  except Exception as exc:
   set_status('reconnecting',socket_connected=False,error=type(exc).__name__)
   time.sleep(30)
