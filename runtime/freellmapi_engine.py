"""Jarvis connector for the authenticated, loopback-only FreeLLMAPI router."""
from pathlib import Path
import json
import httpx
from openjarvis.engine.nim import NIMEngine
from openjarvis.core.registry import EngineRegistry

KEY_PATH = Path.home()/'.openjarvis/freellmapi/router.key'
MODELS = ('freellmapi/auto',)

def route_options(model, options):
    if model not in MODELS:
        raise ValueError('Choose a configured FreeLLMAPI automatic route.')
    if any(k in options for k in ('models', 'plugins', 'route', 'provider', 'base_url', 'api_key')):
        raise ValueError('Provider overrides and billable plugins are disabled.')
    options=dict(options)
    options.setdefault('reasoning_effort','none')
    return 'auto:jarvis', options

@EngineRegistry.register('freellmapi')
class FreeLLMAPIEngine(NIMEngine):
    engine_id = 'freellmapi'
    is_cloud = True
    def __init__(self, **kwargs):
        super().__init__(host='http://127.0.0.1:3001', timeout=180)
        self._api_key = None
        self._client.headers.pop('Authorization', None)
    def _get_headers(self):
        key = KEY_PATH.read_text().strip() if KEY_PATH.exists() else ''
        if not key:
            raise ValueError('Local FreeLLMAPI connection key is missing.')
        return {'Authorization': 'Bearer '+key}
    def health(self):
        try:
            r = self._client.get('/v1/models', headers=self._get_headers(), timeout=2)
            return r.status_code == 200
        except (OSError, ValueError, httpx.HTTPError):
            return False
    def list_models(self):
        return list(MODELS)
    def generate(self, messages, *, model, **kwargs):
        # Keep the agent's synchronous result contract but receive real SSE from
        # the router. A productive stream is no longer a silent whole-response wait.
        from openjarvis.engine._base import messages_to_dicts, estimate_prompt_tokens, EngineConnectionError
        route, options = route_options(model, kwargs)
        payload={'model':route,'messages':messages_to_dicts(messages),**options,
                 'stream':True,'stream_options':{'include_usage':True}}
        if 'tools' in payload and 'tool_choice' not in payload:payload['tool_choice']='auto'
        content=[];calls={};usage={};served=model;finish=None;done=False
        try:
            with self._client.stream('POST','/v1/chat/completions',json=payload,headers=self._get_headers()) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line.startswith('data:'):continue
                    raw=line[5:].strip()
                    if raw=='[DONE]':done=True;break
                    if not raw:continue
                    try:chunk=json.loads(raw)
                    except ValueError as error:raise EngineConnectionError('The model stream contained an invalid chunk.') from error
                    if not isinstance(chunk,dict):raise EngineConnectionError('The model stream contained an invalid message.')
                    if chunk.get('error'):raise EngineConnectionError('The free model could not finish this reply. Please retry.')
                    served=chunk.get('model') or served
                    if chunk.get('usage'):usage=chunk['usage']
                    for choice in chunk.get('choices',[]):
                        if choice.get('index',0)!=0:continue
                        delta=choice.get('delta') or {}
                        if isinstance(delta.get('content'),str):content.append(delta['content'])
                        for part in delta.get('tool_calls') or []:
                            index=part.get('index',0)
                            call=calls.setdefault(index,{'id':'','name':'','arguments':''})
                            if part.get('id'):call['id']=part['id']
                            function=part.get('function') or {}
                            call['name']+=function.get('name') or ''
                            args=function.get('arguments')
                            if isinstance(args,str):call['arguments']+=args
                        if choice.get('finish_reason'):finish=choice['finish_reason']
        except (httpx.ConnectError,httpx.TimeoutException) as error:
            raise EngineConnectionError('The local free-model connection timed out. Please retry.') from error
        if not done and not finish:raise EngineConnectionError('The free model connection ended before completing the reply.')
        prompt=max(usage.get('prompt_tokens') or 0,estimate_prompt_tokens(messages))
        completion=usage.get('completion_tokens') or 0
        result={'content':''.join(content),'model':served,'finish_reason':finish or 'stop',
                'usage':{'prompt_tokens':prompt,'prompt_tokens_evaluated':usage.get('prompt_tokens') or prompt,
                         'completion_tokens':completion,'total_tokens':prompt+completion}}
        if calls:
            if finish!='tool_calls':raise EngineConnectionError('The model did not finish its tool request.')
            result['tool_calls']=[calls[i] for i in sorted(calls)]
            for call in result['tool_calls']:
                if not call['name']:raise EngineConnectionError('The model returned an incomplete tool request.')
                try:arguments=json.loads(call['arguments'] or '{}')
                except ValueError as error:raise EngineConnectionError('The model returned incomplete tool arguments.') from error
                if not isinstance(arguments,dict):raise EngineConnectionError('The model returned invalid tool arguments.')
        return result
    async def stream(self, messages, *, model, **kwargs):
        route, options = route_options(model, kwargs)
        async for item in super().stream(messages, model=route, **options):
            yield item
    async def stream_full(self, messages, *, model, **kwargs):
        route, options = route_options(model, kwargs)
        async for item in super().stream_full(messages, model=route, **options):
            yield item

def attach_router_engine(app):
    from openjarvis.engine.multi import MultiEngine
    from openjarvis.telemetry.instrumented_engine import InstrumentedEngine
    from openjarvis.security.guardrails import GuardrailsEngine
    engine = app.state.engine
    while isinstance(engine, (InstrumentedEngine, GuardrailsEngine)):
        engine = engine._inner if isinstance(engine, InstrumentedEngine) else engine._engine
    if isinstance(engine, MultiEngine) and not any(key == 'freellmapi' for key, _ in engine._engines):
        engine._engines.append(('freellmapi', FreeLLMAPIEngine()))
        engine._refresh_map()
