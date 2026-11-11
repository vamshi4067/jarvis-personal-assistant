"""Responses adapter restricted to validated ChatGPT subscription OAuth."""
import asyncio
import base64
import json
import time
import httpx
import chatgpt_subscription as subscription
from openjarvis.core.registry import EngineRegistry
from openjarvis.engine._base import InferenceEngine, EngineConnectionError, messages_to_dicts, estimate_prompt_tokens
from openjarvis.engine._stubs import StreamChunk

PREFIX='chatgpt-subscription/'

def plan_policy():
    return subscription.read(subscription.ROOT/'policy.json',{})



def payload_for(messages,model,options):
    if not model.startswith(PREFIX):raise ValueError('Choose a ChatGPT subscription model.')
    if any(k in options for k in ('api_key','base_url','provider','models','plugins','route')):
        raise ValueError('API-key billing and alternate providers are disabled for the ChatGPT connection.')
    instructions=[];items=[]
    for message in messages_to_dicts(messages):
        role=message['role'];content=message.get('content') or ''
        if role=='system':instructions.append(str(content));continue
        if role=='tool':
            items.append({'type':'function_call_output','call_id':message['tool_call_id'],'output':str(content)});continue
        if message.get('images'):
            if role!='user':raise ValueError('Images are supported only in user messages on this connection.')
            parts=[{'type':'input_text','text':str(content)}] if content else []
            for value in message['images']:
                if not value.startswith('data:image/'):
                    try:raw=base64.b64decode(value,validate=True)
                    except Exception:raise ValueError('The supplied image is not valid base64.') from None
                    mime=('image/png' if raw.startswith(b'\x89PNG') else 'image/jpeg' if raw.startswith(b'\xff\xd8\xff') else 'image/webp' if raw[:4]==b'RIFF' and raw[8:12]==b'WEBP' else 'image/gif' if raw[:6] in (b'GIF87a',b'GIF89a') else None)
                    if not mime:raise ValueError('Use a PNG, JPEG, GIF or WebP image.')
                    value='data:'+mime+';base64,'+value
                parts.append({'type':'input_image','image_url':value})
            items.append({'role':role,'content':parts})
        elif content:items.append({'role':role,'content':str(content)})
        for call in message.get('tool_calls') or []:
            function=call['function']
            items.append({'type':'function_call','call_id':call['id'],'name':function['name'],
                          'namespace':'jarvis','arguments':function.get('arguments') or '{}'})
    result={'model':model[len(PREFIX):],'input':items,'store':False,'stream':True}
    if instructions:result['instructions']='\n\n'.join(instructions)
    tools=[]
    for tool in options.get('tools') or []:
        if tool.get('type')!='function':raise ValueError('Only Jarvis local function tools are allowed on this subscription route.')
        function=tool.get('function') or {}
        tools.append({'type':'function','name':function['name'],'description':function.get('description',''),
                      'parameters':function.get('parameters',{'type':'object','properties':{}}),'strict':False})
    if tools:result['tools']=[{'type':'namespace','name':'jarvis','description':'Tools executed by the user local Jarvis assistant.','tools':tools}]
    response_format=options.get('response_format')
    if response_format:
        if response_format.get('type')=='json_schema':
            result['text']={'format':{'type':'json_schema',**response_format['json_schema']}}
        elif response_format.get('type')=='json_object':result['text']={'format':{'type':'json_object'}}
    # temperature/max_tokens and other unsupported preview fields are deliberately omitted.
    return result


@EngineRegistry.register('chatgpt-subscription')
class ChatGPTSubscriptionEngine(InferenceEngine):
    engine_id='chatgpt-subscription';is_cloud=True
    def __init__(self,**kwargs):pass
    def list_models(self):
        current=subscription.active()
        if not current:return []
        cached=subscription.read(subscription.ROOT/'models.json',{})
        if cached.get('client_id')!=current['client_id']:return []
        return [m['id'] for m in cached.get('models',[])]
    def health(self):
        current=subscription.active()
        return bool(current and current.get('plan_only_confirmed') and subscription.REQUIRED.issubset(set(current.get('scopes',[]))))
    def generate(self,messages,*,model,**kwargs):
        if plan_policy().get('enabled') and not model.startswith(PREFIX):model=plan_policy().get('model','')
        if model not in self.list_models():raise EngineConnectionError('Refresh your ChatGPT subscription models in Personal before choosing this model.')
        try:
            token=subscription.access_token()
            payload=payload_for(messages,model,kwargs)
            completed=None
            with httpx.Client(timeout=httpx.Timeout(180,connect=15),trust_env=False) as client:
                with client.stream('POST',subscription.RESOURCE+'/responses',headers={'Authorization':'Bearer '+token},json=payload) as response:
                    if response.status_code!=200:
                        if response.status_code==429:raise EngineConnectionError('Your ChatGPT plan limit is reached or temporarily unavailable. Jarvis has stopped; no API-key fallback was used. Review ChatGPT Usage settings.')
                        if response.status_code in (401,403):raise EngineConnectionError('ChatGPT subscription access needs renewed sign-in or plan permission. Reconnect in Personal. No paid fallback was used.')
                        raise EngineConnectionError(f'ChatGPT subscription request failed (HTTP {response.status_code}); no paid fallback was used.')
                    for line in response.iter_lines():
                        if not line.startswith('data:'):continue
                        value=line[5:].strip()
                        if not value or value=='[DONE]':continue
                        event=json.loads(value)
                        kind=event.get('type','')
                        if kind=='response.completed':completed=event.get('response');break
                        if kind in ('response.failed','response.incomplete','error'):
                            error=event.get('response',{}).get('error') or event.get('error') or {}
                            code=error.get('code') if isinstance(error,dict) else None
                            if code in ('subscription_sharing_usage_limit_exceeded','subscription_sharing_usage_unavailable'):
                                raise EngineConnectionError('Your ChatGPT subscription allowance is unavailable or reached its limit. Jarvis stopped without a paid API fallback. Review ChatGPT Usage settings.')
                            raise EngineConnectionError('ChatGPT could not complete this subscription reply. No action or successful response is claimed; no paid fallback was used.')
            if not completed or completed.get('status')!='completed':raise EngineConnectionError('The ChatGPT subscription stream ended without a completed response.')
            content=[];calls=[]
            for item in completed.get('output') or []:
                if item.get('type')=='message':
                    for part in item.get('content') or []:
                        if part.get('type')=='output_text':content.append(part.get('text',''))
                        if part.get('type')=='refusal':content.append(part.get('refusal',''))
                elif item.get('type')=='function_call':
                    if item.get('namespace') not in (None,'jarvis'):raise EngineConnectionError('ChatGPT requested an unknown tool namespace.')
                    args=item.get('arguments') or '{}'
                    if not isinstance(json.loads(args),dict):raise EngineConnectionError('ChatGPT returned invalid tool arguments.')
                    if not item.get('name') or not item.get('call_id'):raise EngineConnectionError('ChatGPT returned an incomplete tool request.')
                    calls.append({'id':item['call_id'],'name':item['name'],'arguments':args})
            usage=completed.get('usage') or {};prompt=max(usage.get('input_tokens') or 0,estimate_prompt_tokens(messages));output=usage.get('output_tokens') or 0
            result={'content':'\n'.join(content),'model':model,'finish_reason':'tool_calls' if calls else 'stop',
                    'usage':{'prompt_tokens':prompt,'prompt_tokens_evaluated':usage.get('input_tokens') or prompt,
                             'completion_tokens':output,'total_tokens':prompt+output}}
            if calls:result['tool_calls']=calls
            return result
        except EngineConnectionError:raise
        except ValueError as error:raise EngineConnectionError(str(error)) from None
        except httpx.HTTPError:raise EngineConnectionError('ChatGPT subscription connection failed. No paid API fallback was used.') from None
    async def stream(self,messages,*,model,**kwargs):
        result=await asyncio.to_thread(self.generate,messages,model=model,**kwargs)
        if result['content']:yield result['content']
    async def stream_full(self,messages,*,model,**kwargs):
        result=await asyncio.to_thread(self.generate,messages,model=model,**kwargs)
        calls=[{'index':i,'id':c['id'],'type':'function','function':{'name':c['name'],'arguments':c['arguments']}} for i,c in enumerate(result.get('tool_calls',[]))]
        yield StreamChunk(content=result['content'] or None,tool_calls=calls or None,finish_reason=result['finish_reason'],usage=result['usage'])
    def close(self):pass


def attach_chatgpt_engine(app):
    from openjarvis.engine.multi import MultiEngine
    from openjarvis.telemetry.instrumented_engine import InstrumentedEngine
    from openjarvis.security.guardrails import GuardrailsEngine
    engine=app.state.engine
    while isinstance(engine,(InstrumentedEngine,GuardrailsEngine)):
        engine=engine._inner if isinstance(engine,InstrumentedEngine) else engine._engine
    if isinstance(engine,MultiEngine) and not any(k=='chatgpt-subscription' for k,_ in engine._engines):
        engine._engines.append(('chatgpt-subscription',ChatGPTSubscriptionEngine()));engine._refresh_map()
