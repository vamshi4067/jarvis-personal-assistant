"""Same-origin browser takeover controls shared with the tool owner thread."""
from urllib.parse import urlsplit
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

class ControlBody(BaseModel):
    mode:str


def install_browser_routes(app):
    from openjarvis.tools import browser
    assistant=browser._jarvis_assistant;owner=browser._jarvis_owner
    def guard(request:Request):
        origin=request.headers.get('origin')
        if origin and urlsplit(origin).netloc!=request.headers.get('host'):raise HTTPException(403,'Use your Jarvis page.')
        if request.method=='POST' and request.headers.get('x-jarvis-personal')!='1':raise HTTPException(403,'Use Jarvis browser controls.')
    router=APIRouter(prefix='/v1/personal/browser',dependencies=[Depends(guard)])
    @router.get('')
    def status():return assistant.status()
    @router.post('/control')
    def control(body:ControlBody):
        if body.mode not in ('human','jarvis'):raise HTTPException(400,'Choose human or jarvis.')
        if body.mode=='human':
            current=assistant.status()
            return assistant.update(control='human',state='pausing' if owner.busy else 'needs_input',stage='Finishing the current step' if owner.busy else 'Your turn in the browser')
        # Returning control waits for the current owner-thread step to finish.
        try:return owner.call(lambda:assistant.set_control(body.mode))
        except Exception:raise HTTPException(503,'Browser is finishing a step. Please try again shortly.')
    before=len(app.router.routes);app.include_router(router)
    app.router.routes[:]=app.router.routes[before:]+app.router.routes[:before]
