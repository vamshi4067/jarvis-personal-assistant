"""OpenRouter tool-capable engine, restricted to zero-priced model routes."""
import json
import time
import logging
from pathlib import Path
import httpx
from openjarvis.engine.nim import NIMEngine
from openjarvis.core.registry import EngineRegistry

KEY_PATH=Path.home()/'.openjarvis/openrouter.key'
PREFERRED='nvidia/nemotron-3.5-lightning:free'
_catalog=[]
_updated=0

def free_request_options(model,kwargs):
    if not (model=='openrouter/free' or model.endswith(':free')):
        raise ValueError('Only OpenRouter free models are enabled. Paid models are blocked.')
    if any(k in kwargs for k in ('models','plugins','route','api_key','base_url')):
        raise ValueError('Paid fallbacks and billable plugins are disabled')
    options=dict(kwargs)
    options['provider']={'max_price':{'prompt':0,'completion':0},'require_parameters':True}
    return options

def free_models():
    global _catalog,_updated
    if _catalog and time.monotonic()-_updated<600:return list(_catalog)
    try:
        r=httpx.get('https://openrouter.ai/api/v1/models',timeout=10)
        r.raise_for_status()
        _catalog=[m['id'] for m in r.json()['data']
            if (m['id'].endswith(':free') or m['id']=='openrouter/free')
            and 'tools' in m.get('supported_parameters',[])
            and all(float(m.get('pricing',{}).get(k,0))==0 for k in ('prompt','completion','request','image'))]
        _updated=time.monotonic()
    except Exception:
        # Never substitute a paid catalog route when discovery is unavailable.
        return list(_catalog) or ['openrouter/free']
    return sorted(_catalog,key=lambda m:(m!=PREFERRED,m!='openrouter/free',m))

@EngineRegistry.register('openrouter-free')
class FreeOpenRouterEngine(NIMEngine):
    engine_id='openrouter-free'
    is_cloud=True
    _api_prefix='/api/v1'
    def __init__(self,**kwargs):
        self._host='https://openrouter.ai'
        self._timeout=180
        self._api_key=None
        self._client=httpx.Client(base_url=self._host,timeout=self._timeout)

    def _get_headers(self):
        key=KEY_PATH.read_text().strip() if KEY_PATH.exists() else ''
        if not key:raise ValueError('Add your OpenRouter key in Personal → Connections. Do not paste it in chat.')
        return {'Authorization':'Bearer '+key,'X-OpenRouter-Title':'Personal Jarvis'}

    def health(self):
        return KEY_PATH.exists() and bool(KEY_PATH.read_text().strip())

    def list_models(self):return free_models()

    def _selected(self,model):
        policy_path=Path.home()/'.openjarvis/chatgpt-subscription/policy.json'
        policy=json.loads(policy_path.read_text()) if policy_path.exists() else {}
        if policy.get('enabled') and policy.get('mode')=='openrouter-free':
            return model if model=='openrouter/free' or model.endswith(':free') else policy.get('model','openrouter/free')
        return model

    def generate(self,messages,*,model,**kwargs):
        from openjarvis.core.live_reply import emit, speech_allowed
        from openjarvis.engine._base import messages_to_dicts, estimate_prompt_tokens, EngineConnectionError
        model=self._selected(model);options=free_request_options(model,kwargs)
        payload={'model':model,'messages':messages_to_dicts(messages),'stream':True,
                 'stream_options':{'include_usage':True},**options}
        if speech_allowed():
            payload.pop('tools',None);payload.pop('tool_choice',None)
            payload['messages']=[{'role':'system','content':'Give a short general explanation in plain prose without Markdown. No tools are available. Do not claim to have performed actions or consulted personal notes.'},*payload['messages']]
        if payload.get('tools') and 'tool_choice' not in payload:payload['tool_choice']='auto'
        pieces=[];calls={};usage={};finish=None;done=False;served=model
        started=time.monotonic();first=None;last_emit=0.;draft='';hidden=False
        emit('start')
        try:
            with self._client.stream('POST',self._api_prefix+'/chat/completions',json=payload,headers=self._get_headers()) as response:
                if response.status_code==429:
                    raise EngineConnectionError('The free OpenRouter limit was reached. Jarvis stopped; no paid fallback was used. Please try later.')
                response.raise_for_status()
                for line in response.iter_lines():
                    from openjarvis.core.live_reply import check_cancelled
                    check_cancelled()
                    if not line.startswith('data:'):continue
                    raw=line[5:].strip()
                    if raw=='[DONE]':done=True;break
                    if not raw:continue
                    event=json.loads(raw)
                    if event.get('error'):raise EngineConnectionError('The free model could not complete this reply. No paid fallback was used.')
                    if event.get('usage'):usage=event['usage']
                    served=event.get('model') or served
                    for choice in event.get('choices',[]):
                        if choice.get('index',0)!=0:continue
                        delta=choice.get('delta') or {}
                        text=delta.get('content')
                        if isinstance(text,str) and text:
                            if first is None:first=time.monotonic()-started
                            pieces.append(text)
                            if not hidden:
                                draft=(draft+text)[:12000]
                                now=time.monotonic()
                                if now-last_emit>=.06:emit('draft',text=draft,speakable=speech_allowed());last_emit=now
                        for part in delta.get('tool_calls') or []:
                            if not hidden:emit('tool');hidden=True
                            call=calls.setdefault(part.get('index',0),{'id':'','name':'','arguments':''})
                            if part.get('id'):call['id']=part['id']
                            function=part.get('function') or {}
                            call['name']+=function.get('name') or ''
                            if isinstance(function.get('arguments'),str):call['arguments']+=function['arguments']
                        if choice.get('finish_reason'):finish=choice['finish_reason']
        except (httpx.ConnectError,httpx.TimeoutException):
            raise EngineConnectionError('The free model connection timed out. No paid fallback was used.') from None
        if not done or finish not in ('stop','tool_calls','length'):
            raise EngineConnectionError('The free model stream ended without a completed reply.')
        if not hidden and draft:emit('draft',text=draft,speakable=speech_allowed())
        prompt=max(usage.get('prompt_tokens') or 0,estimate_prompt_tokens(messages));completion=usage.get('completion_tokens') or 0
        result={'content':''.join(pieces),'model':served,'finish_reason':finish,
                'usage':{'prompt_tokens':prompt,'prompt_tokens_evaluated':usage.get('prompt_tokens') or prompt,
                         'completion_tokens':completion,'total_tokens':prompt+completion}}
        if calls:
            if speech_allowed():raise EngineConnectionError('A tool-free explanation returned an unexpected tool request; no action was executed.')
            if finish!='tool_calls':raise EngineConnectionError('The free model did not finish its tool request.')
            result['tool_calls']=[calls[i] for i in sorted(calls)]
            for call in result['tool_calls']:
                if not call['id'] or not call['name'] or not isinstance(json.loads(call['arguments'] or '{}'),dict):
                    raise EngineConnectionError('The free model returned an incomplete tool request.')
        logging.getLogger('openjarvis.latency').info('OpenRouter first_text_s=%s total_s=%.2f tool_calls=%d',round(first,2) if first is not None else None,time.monotonic()-started,len(calls))
        from response_speed import record
        if first is not None:record('model_first_text',first)
        record('model_total',time.monotonic()-started)
        return result

    async def stream(self,messages,*,model,**kwargs):
        model=self._selected(model)
        async for item in super().stream(messages,model=model,**free_request_options(model,kwargs)):yield item

    async def stream_full(self,messages,*,model,**kwargs):
        model=self._selected(model)
        async for item in super().stream_full(messages,model=model,**free_request_options(model,kwargs)):yield item

def attach_free_engine(app):
    from openjarvis.engine.multi import MultiEngine
    from openjarvis.telemetry.instrumented_engine import InstrumentedEngine
    from openjarvis.security.guardrails import GuardrailsEngine
    engine=app.state.engine
    while isinstance(engine,(InstrumentedEngine,GuardrailsEngine)):
        engine=engine._inner if isinstance(engine,InstrumentedEngine) else engine._engine
    if isinstance(engine,MultiEngine) and not any(key=='openrouter-free' for key,_ in engine._engines):
        engine._engines.append(('openrouter-free',FreeOpenRouterEngine()))
        engine._refresh_map()
