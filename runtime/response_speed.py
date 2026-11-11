"""Local command receipts and content-free latency measurements."""
import json
import logging
import re
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote_plus, urlsplit

_SAMPLES = deque(maxlen=80)
_LOCK = threading.Lock()
SHORT_REPLY_RULE = ('For ordinary conversation, answer in one or two concise sentences unless the user asks for detail. '
                    'Keep facts, qualifications and real action receipts; never invent success to sound quick.')


def record(stage, seconds):
    if stage not in {'model_first_text', 'model_total', 'transcription', 'voice_synthesis', 'local_command', 'first_audio', 'reply_total'}:
        return
    value = float(seconds)
    if not 0 <= value <= 3600:return
    item = {'stage': stage, 'seconds': round(value, 3), 'at': datetime.now(timezone.utc).isoformat()}
    with _LOCK:_SAMPLES.append(item)
    logging.getLogger('openjarvis.latency').info('stage=%s seconds=%.3f', stage, value)


def general_explanation(text):
    """Only self-contained explanations; personal/current/action questions keep tools."""
    if not isinstance(text,str):return False
    text = text.strip()
    if len(text) > 200 or '\n' in text:return False
    if re.search(r'\b(my|our|your|this|that|these|those|it|today|latest|current|now|weather|news|price|stock|file|notes?|email|calendar|remind|open|browse|search|find|remember|save|delete|send|play)\b|https?://|[/\\]', text, re.I):return False
    return bool(re.fullmatch(r'(?:explain|define|what is|what are|how does|how do) [a-zA-Z0-9 ,\-()]{3,160}[?.!]?', text, re.I))


def local_action(agent, text):
    """Exact commands only; all other requests retain the normal agent path."""
    from openjarvis.core.types import ToolCall
    if not isinstance(text,str):return None
    screen_phrase = re.sub(r'^(?:hey[ ,]+)?jarvis\b[ ,:]*', '', text.strip(), flags=re.I).rstrip('.!?')
    if re.fullmatch(r'(?:please )?(?:what am i looking at|(?:look at|look on|check|see) (?:my|the|this) (?:screen|window)(?:[ ,]+(?:and |then )?(?:explain|describe|tell me)\b.*)?)', screen_phrase, re.I):
        return 'Reload Jarvis and ask again to use screen/window sharing in chat. I cannot see your screen until you share it.'
    from routines import run
    receipt = run(text)
    if receipt is not None:return receipt
    started = time.monotonic()
    normalized = re.sub(r'^(?:please\s+)', '', text.strip(), flags=re.I).rstrip('.!?')
    navigation = None
    label = ''
    if re.fullmatch(r'open (?:youtube|you tube)', normalized, re.I):
        navigation = 'https://www.youtube.com/'; label = 'YouTube'
    elif re.fullmatch(r'open google', normalized, re.I):
        navigation = 'https://www.google.com/'; label = 'Google'
    else:
        match = re.fullmatch(r'(?:search (?:the )?web for|google) ([^\n]{1,400})', normalized, re.I)
        if match:navigation = 'https://www.google.com/search?q=' + quote_plus(match[1]);label = 'the search results'
    if navigation:
        # Use the same approval hook and executor as model-selected tools.
        if not hasattr(agent, '_check_tool_allowed') or not hasattr(agent, '_executor'):return None
        tc = ToolCall(id='local_'+str(time.time_ns()), name='browser_navigate', arguments=json.dumps({'url': navigation}))
        denial = agent._check_tool_allowed(tc)
        result = denial if denial is not None else agent._executor.execute(tc)
        record('local_command', time.monotonic() - started)
        if not result.success:return 'Sir, the browser could not confirm that request. Please check the browser or return control to Jarvis.'
        return f'Sir, the browser reports that it opened {label}.'
    match = re.fullmatch(r'remind me in (\d{1,4}|one|two|three|four|five|ten|fifteen|twenty|thirty|sixty) (minutes?|hours?) to (.{1,2000})', normalized, re.I)
    if match:
        numbers={'one':1,'two':2,'three':3,'four':4,'five':5,'ten':10,'fifteen':15,'twenty':20,'thirty':30,'sixty':60}
        n = int(match[1]) if match[1].isdigit() else numbers[match[1].lower()]
        if not 1 <= n <= 1440:return 'Sir, please choose a reminder between one and 1,440 minutes or hours.'
        seconds = n * (3600 if match[2].lower().startswith('hour') else 60)
        from personal_store import PersonalStore
        store = PersonalStore(Path.home()/'.openjarvis/personal.db')
        item = store.add_reminder(match[3], (datetime.now(timezone.utc)+timedelta(seconds=seconds)).isoformat())
        # Read back the actual saved reminder before announcing success.
        with store.connect() as db:
            saved = db.execute('SELECT id FROM reminders WHERE id=?', (item['id'],)).fetchone()
        if not saved:raise RuntimeError('The reminder write was not confirmed.')
        record('local_command', time.monotonic() - started)
        return f'Sir, your reminder is saved for {n} {match[2].lower()} from now. Jarvis must be running to announce it.'
    return None


def install(app):
    from fastapi import APIRouter, HTTPException, Request
    router = APIRouter()
    @router.get('/v1/personal/responsiveness')
    def diagnostics(request: Request):
        if urlsplit('http://'+request.headers.get('host','')).hostname not in ('127.0.0.1','localhost','::1'):raise HTTPException(403)
        with _LOCK: samples=list(_SAMPLES)
        return {'measurements':samples, 'source':'normal use only; no prompts or audio recorded',
                'early_speech':'tool-free general explanations only', 'local_commands':['open YouTube','open Google','search the web for …','remind me in N minutes/hours to …'],
                'wake_behavior_changed':False}
    @router.post('/v1/personal/responsiveness')
    async def measurement(request: Request):
        host=request.headers.get('host','');origin=request.headers.get('origin')
        if request.headers.get('x-jarvis-personal')!='1' or (origin and urlsplit(origin).netloc!=host):raise HTTPException(403)
        body=await request.json()
        try:record(body.get('stage'),body.get('seconds'))
        except (ValueError,TypeError):raise HTTPException(400,'Invalid duration')
        return {'recorded':True}
    before=len(app.router.routes);app.include_router(router)
    app.router.routes[:]=app.router.routes[before:]+app.router.routes[:before]
