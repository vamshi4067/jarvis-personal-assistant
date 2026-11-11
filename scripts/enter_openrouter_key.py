#!/usr/bin/env python3
"""Private terminal entry; no key is echoed or committed."""
from getpass import getpass
from pathlib import Path
import os
value=getpass('Paste your own OpenRouter API key here (hidden), then press Enter: ').strip()
if not value.startswith('sk-or-'):raise SystemExit('That does not look like an OpenRouter key. Nothing saved.')
root=Path.home()/'.openjarvis';root.mkdir(mode=0o700,exist_ok=True)
fd=os.open(root/'openrouter.key',os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
with os.fdopen(fd,'w') as f:f.write(value+'\n')
(root/'openrouter.key').chmod(0o600)
print('Key saved outside the repository. No model request was made.')
