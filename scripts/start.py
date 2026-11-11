#!/usr/bin/env python3
"""Launch an explicitly configured, loopback-only local Jarvis instance."""
from pathlib import Path
import os
import socket
import subprocess
import sys
root=Path.home()/'.openjarvis';runtime=root/'runtime'
python=runtime/'OpenJarvis/.venv/bin/python'
if not python.exists():sys.exit('Install the runtime dependencies first; see docs/SETUP.md.')
with socket.socket() as sock:
 if sock.connect_ex(('127.0.0.1',18766))==0:sys.exit('Port 18766 is already in use. No second server started.')
env=os.environ.copy();env.update(OPENJARVIS_CONFIG=str(root/'openjarvis-personal.toml'),DO_NOT_TRACK='1',HF_HOME=str(root/'models/huggingface'),XDG_CACHE_HOME=str(root/'cache'),PYTORCH_ENABLE_MPS_FALLBACK='1')
raise SystemExit(subprocess.call([str(python),str(runtime/'run-server.py'),'serve','--engine','openrouter-free'],cwd=runtime/'OpenJarvis',env=env))
