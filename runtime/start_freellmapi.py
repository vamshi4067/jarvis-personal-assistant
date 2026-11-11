"""Run the local FreeLLMAPI router; keep provider keys out of arguments/logs."""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path.home() / '.openjarvis'
DATA = ROOT / 'freellmapi'
APP = ROOT / 'runtime/freellmapi'
NODE = Path('/Users/YOUR_NAME/.local/share/pi-node/node-v22.23.1-darwin-arm64/bin/node')

def router_config():
    keys = []
    for platform, filename in [('openrouter', 'openrouter.key'), ('nvidia', 'nvidia.key')]:
        path = ROOT / filename
        if path.exists() and path.read_text().strip():
            keys.append({'platform': platform, 'key': path.read_text().strip(),
                         'label': 'Existing Jarvis connection'})
    return {'keys': keys, 'routing': {'strategy': 'priority'},
            'customProviders': [{'baseUrl': 'http://127.0.0.1:11434/v1',
              'apiKey': 'local-no-key', 'label': 'Jarvis local fallback', 'models': [
                  {'model': 'qwen3.5:0.8b', 'displayName': 'Jarvis local fallback',
                   'supportsTools': True, 'contextWindow': 4096,
                   'intelligenceRank': 900, 'speedRank': 900}]}]}

def main():
    DATA.mkdir(mode=0o700, exist_ok=True)
    with (DATA / 'supervisor.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        env = os.environ.copy()
        for line in (DATA / 'router.env').read_text().splitlines():
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                env[key] = value
        env['FREEAPI_CONFIG_JSON'] = json.dumps(router_config())
        env['PATH'] = str(NODE.parent) + os.pathsep + env.get('PATH', '')
        while True:
            with (DATA / 'router.log').open('a') as log:
                proc = subprocess.Popen([str(NODE), str(APP / 'server/dist/index.js')],
                                        cwd=APP, env=env, stdout=log, stderr=log)
                proc.wait()
            time.sleep(5)

if __name__ == '__main__':
    main()
