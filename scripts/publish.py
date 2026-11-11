#!/usr/bin/env python3
"""Run interactively in YOUR Terminal; no password or token belongs in chat."""
from pathlib import Path
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
ROOT=Path(__file__).resolve().parents[1]
OWNER='vamshi4067'
NAME='jarvis-personal-assistant'
def call(args,**kwargs):return subprocess.run(args,check=True,**kwargs)
def main():
 call([sys.executable,str(ROOT/'scripts/privacy_scan.py'),'--tracked'])
 if subprocess.check_output(['git','-C',str(ROOT),'status','--porcelain']).strip():raise SystemExit('The repository has uncommitted files. Review and commit them before publishing.')
 gh=shutil.which('gh')
 if not gh:
  if (platform.system(),platform.machine())!=('Darwin','arm64'):raise SystemExit('Install GitHub CLI from https://cli.github.com and run this helper again.')
  version='2.103.3';name=f'gh_{version}_macOS_arm64.zip'
  with tempfile.TemporaryDirectory(prefix='jarvis-github-cli-') as folder:
   archive=Path(folder)/name
   urllib.request.urlretrieve(f'https://github.com/cli/cli/releases/download/v{version}/{name}',archive)
   if hashlib.sha256(archive.read_bytes()).hexdigest()!='d700207eae9ae98fe2b89535c2c087c07823d4628c56364695a5a07ef311c062':raise SystemExit('GitHub CLI checksum mismatch; nothing executed.')
   with zipfile.ZipFile(archive) as z:
    entry=next(n for n in z.namelist() if n.endswith('/bin/gh'))
    binary=Path(folder)/'gh';binary.write_bytes(z.read(entry));binary.chmod(0o700)
   publish(str(binary))
 else:publish(gh)
def publish(gh):
 env={**os.environ,'PATH':str(Path(gh).parent)+os.pathsep+os.environ.get('PATH','')}
 # Use a standard browser sign-in; GitHub handles credentials, never this repository.
 if subprocess.run([gh,'auth','status','--hostname','github.com'],env=env).returncode:
  call([gh,'auth','login','--hostname','github.com','--git-protocol','https','--web'],env=env)
 login=subprocess.check_output([gh,'api','user','--jq','.login'],env=env,text=True).strip()
 if login!=OWNER:raise SystemExit(f'Signed in as {login}; expected {OWNER}. No repository created.')
 if subprocess.run([gh,'repo','view',OWNER+'/'+NAME],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0:
  raise SystemExit('That repository already exists. Nothing overwritten. Review it in GitHub before continuing.')
 call([gh,'repo','create',OWNER+'/'+NAME,'--private','--source',str(ROOT),'--remote','origin','--description','Local-first Jarvis assistant: voice, routines, screen snapshots and knowledge galaxy. Sanitized source export.'],env=env)
 call(['git','-C',str(ROOT),'-c','credential.helper=','-c','credential.helper=!gh auth git-credential','push','-u','origin','main'],env=env)
 print('\nPublished privately: https://github.com/'+OWNER+'/'+NAME)
 print('Review repository contents and media before choosing whether to make it public.')
if __name__=='__main__':main()
