"""Free, visible Jarvis browser with one thread owning all Playwright objects."""
from concurrent.futures import Future
from functools import wraps
from pathlib import Path
from queue import Queue, Empty
from threading import Thread, get_ident
from urllib.parse import quote_plus
import atexit
import json
import time


def youtube_search_url(query):
    return 'https://www.youtube.com/results?search_query=' + quote_plus(query)


def playback_confirmed(before, status):
    return bool(status and not status.get('paused', True)
                and not status.get('ended', True) and not status.get('ad', False)
                and status.get('currentTime', 0) > before + .1)


def main_video(page):
    player = page.locator('#movie_player video')
    return player.first if player.count() else page.locator('video').first


def skip_available_ad(page):
    buttons = page.locator('button.ytp-skip-ad-button, button.ytp-ad-skip-button, '
                          'button.ytp-ad-skip-button-modern, button.ytp-ad-skip-button-slot')
    for button in buttons.all():
        if button.is_visible():
            button.click(timeout=2000)
            return True
    return False


class BrowserOwner:
    """Agent tools run on several workers; Playwright must stay on one thread."""
    def __init__(self):
        self.queue = Queue(maxsize=16)
        self.ident = None
        self.on_idle = None
        self.on_finish = None
        self.busy = False
        self.thread = Thread(target=self._run, name='jarvis-browser', daemon=True)
        self.thread.start()

    def _run(self):
        self.ident = get_ident()
        while True:
            try:
                item = self.queue.get(timeout=.75)
            except Empty:
                if self.on_idle:
                    try:
                        self.busy=True
                        self.on_idle()
                    except Exception:
                        pass  # Page can close or navigate between idle checks.
                    finally:
                        self.busy=False
                        if self.on_finish:self.on_finish()
                continue
            if item is None:
                return
            function, future = item
            if not future.set_running_or_notify_cancel():
                continue
            try:
                self.busy=True
                future.set_result(function())
            except BaseException as error:
                future.set_exception(error)
            finally:
                self.busy=False
                if self.on_finish:self.on_finish()

    def call(self, function):
        if get_ident() == self.ident:
            return function()
        future = Future()
        self.queue.put((function, future), timeout=2)
        try:return future.result(timeout=65)
        except TimeoutError:
            future.cancel()
            raise

    def close(self):
        self.queue.put(None, timeout=2)
        self.thread.join(timeout=2)


_VIDEO_STATUS = """() => {
 const v=document.querySelector('#movie_player video') || document.querySelector('video');
 return v ? {paused:v.paused,ended:v.ended,currentTime:v.currentTime,
   ad:!!document.querySelector('.ad-showing'),title:document.title,url:location.href} : null;
}"""


def install_browser_tools():
    import openjarvis.tools
    from openjarvis.tools import browser
    from openjarvis.core.registry import ToolRegistry
    from openjarvis.core.types import ToolResult
    from openjarvis.tools._stubs import BaseTool, ToolSpec

    if getattr(browser, '_jarvis_visible_installed', False):
        return
    owner = BrowserOwner()
    session = browser._session
    from browser_observation import BrowserAssistant
    assistant = BrowserAssistant(session)
    browser._jarvis_assistant = assistant
    browser._jarvis_owner = owner
    def finish_step():
        if assistant.status()['control']=='human':assistant.update(state='needs_input',stage='Your turn in the browser')
    owner.on_finish=finish_step

    def ensure_visible():
        if session._page is not None:
            try:
                if not session._page.is_closed():
                    return
            except Exception:
                pass
        session.close()
        from playwright.sync_api import sync_playwright
        profile = Path.home()/'.openjarvis/runtime/browser-profile'
        profile.mkdir(parents=True, exist_ok=True, mode=0o700)
        session._playwright = sync_playwright().start()
        session._browser = session._playwright.chromium.launch_persistent_context(
            str(profile), headless=False, viewport={'width': 1280, 'height': 800},
        )
        session._page = (session._browser.pages or [session._browser.new_page()])[0]
        session._page.set_default_timeout(12000)
        session._page.set_default_navigation_timeout(25000)

    session._ensure_browser = ensure_visible

    # Entire tool calls, including locator operations, stay on the owner thread.
    for name in ('browser_navigate', 'browser_click', 'browser_type',
                 'browser_extract', 'browser_screenshot', 'browser_axtree'):
        cls = ToolRegistry.get(name)
        original = cls.execute

        def wrap(function, tool_name):
            @wraps(function)
            def execute(self, **params):
                def grounded():
                    assistant.require_control()
                    assistant.update(state='working',stage='Using the browser')
                    result=function(self, **params)
                    if assistant.status()['control']=='human':
                        assistant.update(state='needs_input',stage='Your turn in the browser')
                        return result
                    if tool_name in ('browser_navigate','browser_click','browser_type'):
                        observation=assistant.observe()
                        return ToolResult(tool_name=tool_name,success=result.success,
                            content=result.content+'\nCurrent page evidence: '+json.dumps(observation),
                            metadata={**(result.metadata or {}),'observation':observation,'goal_completed':False})
                    assistant.update(state='observed',stage='Browser step finished')
                    return result
                try:return owner.call(grounded)
                except ValueError as error:
                    assistant.update(state='needs_input' if assistant.status()['control']=='human' else 'failed',stage='Your turn in the browser' if assistant.status()['control']=='human' else 'Observe again or take control')
                    return ToolResult(tool_name=tool_name,success=False,content=str(error))
                except Exception:return ToolResult(tool_name=tool_name,success=False,content='Browser step could not finish. Observe the page again or take control.')
            return execute
        cls.execute = wrap(original,name)

    @ToolRegistry.register('browser_assist')
    class BrowserAssistTool(BaseTool):
        tool_id='browser_assist'
        is_local=False
        @property
        def spec(self):
            return ToolSpec(name=self.tool_id,category='browser',timeout_seconds=70,
                description='Observe the current browser and act on fresh control references. Use observe before click/type, with ref from that snapshot. Reobserve after page changes. Use takeover to pause for user login/verification; only the user can Return control from the browser card. A performed click is not proof the task finished. Never type credentials or automate CAPTCHA.',
                parameters={'type':'object','properties':{'action':{'type':'string','enum':['observe','click','type','takeover','status']},'ref':{'type':'string'},'text':{'type':'string'}},'required':['action']},required_capabilities=['network:fetch'])
        def execute(self,**params):
            try:
                result=owner.call(lambda:assistant.execute(params.get('action'),params.get('ref'),params.get('text')))
                return ToolResult(tool_name=self.tool_id,success=True,content=json.dumps(result))
            except ValueError as error:
                assistant.update(state='needs_input' if assistant.status()['control']=='human' else 'failed',stage='Your turn in the browser' if assistant.status()['control']=='human' else 'Observe again or take control')
                return ToolResult(tool_name=self.tool_id,success=False,content=str(error))
            except Exception:return ToolResult(tool_name=self.tool_id,success=False,content='Browser observation unavailable. The page may have closed; try opening it again.')

    @ToolRegistry.register('browser_media')
    class BrowserMediaTool(BaseTool):
        tool_id = 'browser_media'
        is_local = False

        @property
        def spec(self):
            return ToolSpec(
                name='browser_media', category='browser', timeout_seconds=70,
                description=(
                    'Control YouTube in Jarvis\'s visible browser. Use play to search '
                    'and play the requested song/video (first result by default), '
                    'search to show results, pause/resume to control playback, '
                    'skip_ad to click the normal Skip ad button, status to verify it. '
                    'Available Skip ad buttons are clicked automatically. '
                    'For "go to Music and play the first song", '
                    'use action=play, query=music. Playback is checked, not assumed.'
                ),
                parameters={'type': 'object', 'properties': {
                    'action': {'type': 'string', 'enum': ['play', 'search', 'pause', 'resume', 'skip_ad', 'status']},
                    'query': {'type': 'string', 'description': 'Song, artist, or video search words.'},
                    'result_number': {'type': 'integer', 'minimum': 1, 'maximum': 10},
                }, 'required': ['action']},
                required_capabilities=['network:fetch'],
            )

        def execute(self, **params):
            try:
                def controlled():
                    assistant.require_control()
                    assistant.update(state='working',stage='Using the media player')
                    result=self._execute(**params)
                    if assistant.status()['control']!='human':assistant.update(state='observed',stage='Media step finished')
                    return result
                return owner.call(controlled)
            except Exception as error:
                return ToolResult(tool_name=self.tool_id, success=False,
                    content=f'Browser media failed: {type(error).__name__}: {error}')

        def _execute(self, **params):
            action = params.get('action')
            if action not in ('play', 'search', 'pause', 'resume', 'skip_ad', 'status'):
                return ToolResult(tool_name=self.tool_id, success=False, content='Unknown media action.')
            page = session.page
            page.bring_to_front()
            if action in ('play', 'search'):
                query = str(params.get('query') or 'music')[:500]
                number = max(1, min(10, int(params.get('result_number', 1))))
                page.goto(youtube_search_url(query), wait_until='domcontentloaded')
                # Return a real blocker if consent, login, or CAPTCHA prevents results.
                videos = page.locator('ytd-video-renderer a#video-title')
                videos.first.wait_for(state='visible')
                if action == 'search':
                    titles = videos.all_text_contents()[:10]
                    return ToolResult(tool_name=self.tool_id, success=True,
                        content='Opened YouTube results: '+json.dumps(titles), metadata={'url':page.url})
                videos.nth(number-1).click()
                page.wait_for_selector('video', state='attached')
            if action == 'pause':
                main_video(page).evaluate('(v) => v.pause()')
            elif action in ('play', 'resume', 'skip_ad'):
                # A real player click provides the browser's ordinary media gesture.
                play = page.locator('#movie_player .ytp-play-button').first
                if main_video(page).evaluate('(v) => v.paused'):
                    play.click()
            status = page.evaluate(_VIDEO_STATUS)
            confirmed = False
            skipped = False
            if action in ('play', 'resume', 'skip_ad') and status:
                deadline = time.monotonic() + 20
                before = status['currentTime']
                while time.monotonic() < deadline:
                    if skip_available_ad(page):
                        skipped = True
                    page.wait_for_timeout(400)
                    current = page.evaluate(_VIDEO_STATUS)
                    if current and not current.get('ad'):
                        if not status.get('ad') and playback_confirmed(before, current):
                            status = current
                            confirmed = True
                            break
                        before = current['currentTime']
                    status = current or status
            if action == 'status' and status:
                before = status['currentTime']
                try:
                    page.wait_for_function('before => {const v=document.querySelector("#movie_player video") || document.querySelector("video");return v && !v.paused && v.currentTime > before+.2}', arg=before, timeout=2000)
                except Exception:
                    pass
                status = page.evaluate(_VIDEO_STATUS)
                confirmed = playback_confirmed(before, status)
            success = bool(status) and (action not in ('play', 'resume', 'skip_ad') or confirmed or skipped)
            content = json.dumps({'action':action,'playback_confirmed':confirmed,'ad_skipped':skipped,'video':status})
            if status and status.get('ad'):
                content += '\nAn advertisement is playing; requested content playback is not confirmed.'
            return ToolResult(tool_name=self.tool_id, success=success, content=content)

    browser._jarvis_visible_installed = True

    def skip_on_idle():
        if assistant.status()['control']=='human':return
        page = session._page
        if page is not None and not page.is_closed():
            from urllib.parse import urlparse
            host = urlparse(page.url).hostname or ''
            if host in ('www.youtube.com', 'youtube.com', 'music.youtube.com'):
                skip_available_ad(page)
    owner.on_idle = skip_on_idle

    def shutdown():
        try:
            owner.call(session.close)
        finally:
            owner.close()
    atexit.register(shutdown)
