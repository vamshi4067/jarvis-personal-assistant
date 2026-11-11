"""Shared research service for Jarvis's agent tool and Personal report library."""
import json
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from research_reports import ReportService

_service=None


class ReportBody(BaseModel):
    topic:str=Field(min_length=3,max_length=1000)


def build_report_router(service):
    def guard(request:Request):
        origin=request.headers.get('origin')
        if origin and urlsplit(origin).netloc!=request.headers.get('host'):
            raise HTTPException(403,'Open reports from your Jarvis page.')
        if request.method not in ('GET','HEAD','OPTIONS') and request.headers.get('x-jarvis-personal')!='1':
            raise HTTPException(403,'Use Jarvis Personal or its local API client.')
    router=APIRouter(prefix='/v1/personal/reports',tags=['research reports'],dependencies=[Depends(guard)])

    @router.get('')
    def list_reports():return service.list_reports()

    @router.post('',status_code=202)
    def create_report(body:ReportBody):
        try:return service.start(body.topic)
        except ValueError as error:raise HTTPException(429 if 'queue' in str(error) else 400,str(error))

    @router.get('/{id}')
    def get_report(id:str):
        try:return service.get(id)
        except ValueError as error:raise HTTPException(400,str(error))
        except KeyError:raise HTTPException(404,'Report not found.')

    @router.post('/{id}/cancel')
    def cancel(id:str):
        try:return service.cancel(id)
        except (ValueError,KeyError):raise HTTPException(404,'Report not found.')

    @router.post('/{id}/retry',status_code=202)
    def retry(id:str):
        try:return service.retry(id)
        except KeyError:raise HTTPException(404,'Report not found.')
        except ValueError as error:raise HTTPException(409,str(error))

    @router.get('/{id}/download/{format}')
    def download(id:str,format:str):
        if format not in ('pdf','docx'):raise HTTPException(400,'Choose PDF or Word.')
        try:path=service.download_path(id,format);job=service.get(id)
        except KeyError:raise HTTPException(404,'Report not found.')
        except ValueError as error:raise HTTPException(400 if 'ID' in str(error) else 409,str(error))
        media='application/pdf' if format=='pdf' else 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        return FileResponse(path,media_type=media,filename=job['title']+'.'+format,headers={'Cache-Control':'no-store'})
    return router


def register_research_tool():
    from openjarvis.core.registry import ToolRegistry
    from openjarvis.core.types import ToolResult
    from openjarvis.tools._stubs import BaseTool, ToolSpec
    if 'research_report' in ToolRegistry.keys():return

    @ToolRegistry.register('research_report')
    class ResearchReportTool(BaseTool):
        tool_id='research_report'
        is_local=False

        @property
        def spec(self):
            return ToolSpec(name=self.tool_id,category='research',timeout_seconds=10,
                description=(
                    'Research a topic and CREATE a saved, cited PDF plus editable Word report. '
                    'Use action=create with topic for research-and-create requests. cancel stops at the next safe stage; retry creates a new job from a failed/cancelled topic. Runs in the background; '
                    'return the job ID and direct the user to Personal → Research and create. '
                    'Respond immediately after creation; do not repeatedly poll. Use action=status with report_id when the user asks to check progress. Do not claim a queued report '
                    'is complete. A short summary is announced when it finishes in the open web app.'
                ),
                parameters={'type':'object','properties':{
                    'action':{'type':'string','enum':['create','status','cancel','retry']},
                    'topic':{'type':'string'},'report_id':{'type':'string'},
                },'required':['action']},required_capabilities=['network:fetch'])

        def execute(self,**params):
            if _service is None:return ToolResult(tool_name=self.tool_id,success=False,content='The report service is not available yet.')
            try:
                action=params.get('action')
                if action=='create':job=_service.start(params.get('topic',''))
                elif action=='status':job=_service.get(params.get('report_id',''))
                elif action=='cancel':job=_service.cancel(params.get('report_id',''))
                elif action=='retry':job=_service.retry(params.get('report_id',''))
                else:raise ValueError('Choose create or status.')
                job={**job,'library':'/personal?report='+job['id']}
                return ToolResult(tool_name=self.tool_id,success=True,content=json.dumps(job,ensure_ascii=False))
            except (KeyError,ValueError) as error:
                return ToolResult(tool_name=self.tool_id,success=False,content=str(error))


def report_response_format():
    def obj(properties):
        return {'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}
    paragraph=obj({'text':{'type':'string'},'sources':{'type':'array','items':{'type':'integer'}}})
    section=obj({'heading':{'type':'string'},'paragraphs':{'type':'array','items':paragraph}})
    schema=obj({'title':{'type':'string'},'summary':paragraph,
                'sections':{'type':'array','items':section},'limitations':{'type':'string'}})
    return {'type':'json_schema','json_schema':{'name':'research_report','strict':True,'schema':schema}}


def draft_with_engine(engine,prompt):
    from openjarvis.core.types import Message, Role
    result=engine.generate([
        Message(role=Role.SYSTEM,content='Return only the final evidence-based research report as valid JSON. Do not include analysis or reasoning in the report.'),
        Message(role=Role.USER,content=prompt),
    ],model='freellmapi/auto',temperature=.2,max_tokens=6500,
      response_format=report_response_format(),reasoning_effort='none')
    return result.get('content','')


def install_research(app):
    global _service
    from openjarvis.tools.web_search import WebSearchTool
    # Reports must not silently switch to a billable search API if keys are added.
    from research_web import ResearchWeb
    search=ResearchWeb(WebSearchTool(engine='duckduckgo'))
    engine=app.state.engine

    def draft(prompt):
        return draft_with_engine(engine,prompt)

    _service=ReportService(Path.home()/'.openjarvis/reports',search.execute,draft)
    app.state.reports=_service
    before=len(app.router.routes)
    app.include_router(build_report_router(_service))
    app.router.routes[:]=app.router.routes[before:]+app.router.routes[:before]
