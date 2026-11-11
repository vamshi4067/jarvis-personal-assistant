"""Website-only REA adapter. Standard library only; never executes site code."""
import ipaddress
import http.client
import ssl
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import tempfile
import sys
import contextlib
import threading
import time
from html.parser import HTMLParser
from urllib.parse import urlsplit, urljoin
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler, HTTPHandler, HTTPSHandler

HOME = Path.home() / '.jarvis-tools' / 'rea'
CLI = HOME / 'node_modules/rea-agents/scripts/rea.mjs'
_OBSERVATION_LOCK = threading.Lock()


def node_candidates():
    yield from HOME.glob('node-v*/bin/node')
    for item in (shutil.which('node'), '/opt/homebrew/bin/node', '/usr/local/bin/node',
                 str(Path.home() / '.volta/bin/node'),
                 str(Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'nodejs/node.exe')):
        if item:
            yield Path(item)
    yield from (Path.home() / '.nvm/versions/node').glob('*/bin/node')
    yield from (Path.home() / '.local/share/pi-node').glob('*/bin/node')


def find_node():
    for path in node_candidates():
        if not path.is_file():
            continue
        try:
            version = subprocess.check_output([str(path.resolve()), '--version'], timeout=5, text=True).strip()
            parts = tuple(map(int, version.lstrip('v').split('.')[:3]))
            # rea-agents 6.8.0's actual engine requirement exceeds the older minimum.
            if ((parts[0] == 22 and parts >= (22, 23, 4)) or
                (parts[0] == 24 and parts >= (24, 22, 1)) or parts >= (26, 12, 1)):
                return str(path.resolve()), version
        except (OSError, ValueError, subprocess.SubprocessError):
            continue
    return None, None


def find_chrome():
    candidates = [Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'),
                  Path.home() / 'Applications/Google Chrome.app/Contents/MacOS/Google Chrome']
    for key in ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'LOCALAPPDATA'):
        if os.environ.get(key):
            candidates.append(Path(os.environ[key]) / 'Google/Chrome/Application/chrome.exe')
    return next((str(p) for p in candidates if p.is_file()), None)


def diagnostics():
    problems = []
    installed = pinned = None
    try:
        installed = json.loads((HOME / 'node_modules/rea-agents/package.json').read_text())['version']
        pinned = json.loads((HOME / 'package.json').read_text())['dependencies']['rea-agents']
        locked = json.loads((HOME / 'package-lock.json').read_text())['packages']['node_modules/rea-agents']['version']
        if pinned != installed or locked != pinned or not re.fullmatch(r'\d+\.\d+\.\d+', pinned):
            problems.append('Reinstall REA with an exact version matching its lockfile.')
        if installed != '6.8.0':
            problems.append('This adapter supports pinned REA 6.8.0; review the adapter before upgrading.')
    except (OSError, KeyError, ValueError):
        problems.append('Install rea-agents 6.8.0 with --save-exact --ignore-scripts in ~/.jarvis-tools/rea.')
    node, version = find_node()
    if not node:
        problems.append('Install Node.js 22.23.4 or a compatible newer release required by REA 6.8.0.')
    chrome = find_chrome()
    if not chrome:
        problems.append('Install Google Chrome for Mac or Windows.')
    if not CLI.is_file():
        problems.append('Reinstall REA: its command-line entry point is missing.')
    if node and CLI.is_file() and not problems:
        try:
            result = subprocess.run([node, str(CLI), '--version', '--json'], capture_output=True, text=True, timeout=15)
            if result.returncode or installed not in result.stdout:
                problems.append('REA cannot start; reinstall its pinned package and dependencies.')
        except (OSError, subprocess.SubprocessError):
            problems.append('REA did not start; check its private Node installation.')
    return {'ready': not problems, 'installed_version': installed, 'pinned_version': pinned,
            'node_version': version, 'node_path': node, 'chrome_found': bool(chrome),
            'chrome_path': chrome, 'problems': problems, 'mode': 'static-public-website-observation'}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def validate_url(url):
    parsed = urlsplit(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Use a public HTTP or HTTPS website without credentials.')
    if parsed.port not in (None, 80, 443):
        raise ValueError('Use a public website on port 80 or 443.')
    addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80), type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError('This kit observes public websites only; private addresses and local services are excluded.')
    return parsed, addresses[0][4][0]


def fetch(url, limit, deadline):
    # No browser profile, cookies, credentials, proxy inheritance or automatic redirects.
    for _ in range(6):
        if time.monotonic() >= deadline:
            raise ValueError('Website source collection timed out.')
        parsed, address = validate_url(url)
        # Connect to the exact vetted IP; retain the hostname for TLS validation.
        class PinnedHTTP(http.client.HTTPConnection):
            def connect(self):
                self.sock = socket.create_connection((address, self.port), self.timeout)
        class PinnedHTTPS(http.client.HTTPSConnection):
            def connect(self):
                raw = socket.create_connection((address, self.port), self.timeout)
                try:
                    self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
                except BaseException:
                    raw.close(); raise
        class ReadHTTP(HTTPHandler):
            def http_open(self, req):
                return self.do_open(PinnedHTTP, req)
        class ReadHTTPS(HTTPSHandler):
            def https_open(self, req):
                return self.do_open(PinnedHTTPS, req, context=ssl.create_default_context())
        opener = build_opener(ProxyHandler({}), NoRedirect(), ReadHTTP(), ReadHTTPS())
        try:
            response = opener.open(Request(url, headers={'User-Agent': 'Jarvis-REA-Observer/1.0'}), timeout=max(0.1, min(15, deadline - time.monotonic())))
        except Exception as error:
            from urllib.error import HTTPError
            if isinstance(error, HTTPError) and error.code in (301, 302, 303, 307, 308):
                target = error.headers.get('Location')
                error.close()
                if not target:
                    raise ValueError('The website returned an invalid redirect.')
                url = urljoin(url, target)
                continue
            raise
        with response:
            chunks = []; size = 0
            while size <= limit:
                if time.monotonic() >= deadline:
                    raise ValueError('Website source collection timed out.')
                chunk = response.read1(min(65536, limit + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk); size += len(chunk)
            data = b''.join(chunks)
            if len(data) > limit:
                raise ValueError('The website source exceeds the observation size limit.')
            return url, data, response.headers.get_content_type()
    raise ValueError('The website redirected too many times.')


class Scripts(HTMLParser):
    def __init__(self):
        super().__init__(); self.sources = []; self.inline = []; self.current = None
    def handle_starttag(self, tag, attrs):
        if tag == 'script':
            attrs = dict(attrs)
            if attrs.get('src'):
                self.sources.append(attrs['src']); self.current = None
            elif attrs.get('type', '').lower() in ('', 'module', 'text/javascript', 'application/javascript'):
                self.current = []
    def handle_data(self, data):
        if self.current is not None:
            self.current.append(data)
    def handle_endtag(self, tag):
        if tag == 'script' and self.current is not None:
            self.inline.append(''.join(self.current)); self.current = None


def _observe_website(url):
    status = diagnostics()
    if not status['ready']:
        return {'success': False, 'message': 'Sir, the observation bay needs attention: ' + ' '.join(status['problems'])}
    try:
        deadline = time.monotonic() + 60
        final, html, content_type = fetch(url, 2_000_000, deadline)
        if content_type not in ('text/html', 'application/xhtml+xml'):
            raise ValueError('Please provide a website page returning HTML.')
        parser = Scripts(); parser.feed(html.decode('utf-8', errors='replace'))
        root = HOME / 'observations'; root.mkdir(exist_ok=True)
        with contextlib.nullcontext(tempfile.mkdtemp(prefix='website-', dir=root)) as directory:
            source = Path(directory) / 'source'; source.mkdir()
            (source / 'page.html').write_bytes(html)
            fetched = []; limitations = ['Static source observation only; no site code was executed, no authenticated state was accessed, and runtime behaviour is unverified.']
            for index, script in enumerate(parser.inline[:8]):
                (source / f'inline-{index}.js').write_text(script)
            origin = urlsplit(final)
            for index, relative in enumerate(list(dict.fromkeys(parser.sources))[:8]):
                target = urljoin(final, relative)
                if urlsplit(target).netloc != origin.netloc or urlsplit(target).scheme != origin.scheme:
                    limitations.append('A cross-origin script was excluded.'); continue
                try:
                    actual, data, kind = fetch(target, 1_000_000, deadline)
                    if urlsplit(actual).netloc != origin.netloc or urlsplit(actual).scheme != origin.scheme:
                        raise ValueError('Cross-origin redirect excluded.')
                    if kind not in ('text/javascript', 'application/javascript', 'application/x-javascript', 'text/plain'):
                        raise ValueError('Non-JavaScript resource excluded.')
                    (source / f'external-{index}.js').write_bytes(data); fetched.append(actual)
                except Exception:
                    limitations.append('A linked script could not be read and was excluded.')
            evidence = Path(directory) / 'evidence.json'
            command = [status['node_path'], str(CLI), 'analyze-javascript-application', str(source),
                       '--detail', 'summary', '--evidence_output', str(evidence),
                       '--max-heap-mb', '512', '--analysis-timeout-ms', '20000', '--json']
            with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
                process = subprocess.Popen(command, stdout=output, stderr=errors, stdin=subprocess.DEVNULL,
                                           start_new_session=False)
                try:
                    process.wait(timeout=90)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(); raise ValueError('Observation timed out; no completed analysis is available.')
                output.seek(0); result = output.read(2_000_001)
                if process.returncode or len(result) > 2_000_000:
                    raise ValueError('REA could not complete this bounded website analysis.')
                analysis = json.loads(result)
            return {'success': True, 'url': final, 'scripts_observed': len(fetched) + min(8, len(parser.inline)),
                    'limitations': limitations, 'evidence': analysis,
                    'receipt': {'operation': 'static_website_observation', 'rea_version': status['installed_version'], 'site_actions_performed': False, 'evidence_path': str(evidence)}}
    except Exception as error:
        message = str(error) if isinstance(error, ValueError) else 'The website could not be read; no completed observation is available.'
        return {'success': False, 'message': 'Sir, ' + message}


def observe_website(url):
    if not _OBSERVATION_LOCK.acquire(blocking=False):
        return {'success': False, 'message': 'Sir, one website observation is already in progress; please let it finish.'}
    try:
        if not isinstance(url, str) or len(url) > 4000:
            return {'success': False, 'message': 'Sir, please provide a website URL.'}
        # A separate bounded process also caps DNS and slow network reads.
        with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
            process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--observe', url],
                                       stdout=output, stderr=errors, stdin=subprocess.DEVNULL,
                                       start_new_session=True)
            try:
                process.wait(timeout=180)
                output.seek(0); data = output.read(2_100_001)
                if process.returncode or len(data) > 2_100_000:
                    raise ValueError('REA did not return a completed observation.')
                return json.loads(data)
            except (ValueError, subprocess.SubprocessError):
                return {'success': False, 'message': 'Sir, the website observation failed or timed out; no completed result is available.'}
            finally:
                if os.name == 'posix':
                    import signal
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                elif process.poll() is None:
                    process.kill()
                process.wait()
    except OSError:
        return {'success': False, 'message': 'Sir, the observation worker could not start; please repair the optional REA adapter.'}
    finally:
        _OBSERVATION_LOCK.release()


if __name__ == '__main__' and len(sys.argv) == 3 and sys.argv[1] == '--observe':
    print(json.dumps(_observe_website(sys.argv[2])))
