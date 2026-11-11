#!/usr/bin/env python3
"""Scan files or Git blobs without printing matched secret values."""
import argparse
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
PATTERNS={
 'provider token':rb'(?:sk-or-v1-[a-fA-F0-9]{48,}|sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{40,}|nvapi-[A-Za-z0-9_-]{24,}|xox[baprs]-[A-Za-z0-9-]{16,}|xapp-[A-Za-z0-9-]{20,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{35,})',
 'private key':rb'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----',
 'JWT token':rb'eyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{24,}\.[A-Za-z0-9_-]{16,}',
 'personal inbox link':rb'https://mail\.google\.com/mail/u/[1-9][0-9]*/',
 'personal LinkedIn highlights':rb'highlighted' + rb'Urns=',
 'private calendar link':rb'https://calendar\.google\.com/calendar/ical/[^\s"<>]*private-[^\s"<>]+',
 'private phone pairing':rb'https://ntfy\.sh/jarvis-[A-Za-z0-9_-]{32}',
}
FORBIDDEN={'.env','routines.json','work-handoff.json','personal-integrations.json','slack-bot.json','phone-alerts.json','login-pending.json','openjarvis-personal.toml'}
def git(*args):return subprocess.check_output(['git','-C',str(ROOT),*args])
def files(mode):
 if mode=='staged':
  names=git('diff','--cached','--name-only','--diff-filter=ACMR','-z').split(b'\0')
  for raw in names:
   if raw:
    name=raw.decode();yield name,git('show',':'+name)
 elif mode=='tracked':
  for raw in git('ls-files','-z').split(b'\0'):
   if raw:
    name=raw.decode();p=ROOT/name
    if p.is_file():yield name,subprocess.check_output(["cat",str(p)])
 else:
  for p in ROOT.rglob('*'):
   if p.is_file() and '.git' not in p.relative_to(ROOT).parts:
    if p.is_symlink():yield str(p.relative_to(ROOT)),b'';continue
    yield str(p.relative_to(ROOT)),subprocess.check_output(["cat",str(p)])
def main():
 parser=argparse.ArgumentParser();g=parser.add_mutually_exclusive_group();g.add_argument('--tracked',action='store_true');g.add_argument('--staged',action='store_true');args=parser.parse_args()
 findings=[];count=0
 for name,data in files('staged' if args.staged else 'tracked' if args.tracked else 'all'):
  count+=1;p=Path(name)
  if p.name in FORBIDDEN or p.suffix.lower() in {'.key','.pem','.db','.sqlite','.log'} or any(x in p.parts for x in ('browser-profile','.venv','node_modules','accounts','__pycache__')):
   findings.append((name,'private runtime file'))
  if (ROOT/name).is_symlink():findings.append((name,'symlink requires review'))
  for label,pattern in PATTERNS.items():
   if re.search(pattern,data):findings.append((name,label))
  # The home directory used during development is private; placeholders are OK.
  if re.search(rb'/Users/(?!YOUR_NAME(?:/|\b)|example(?:/|\b)|user(?:/|\b)|username(?:/|\b)|test(?:/|\b)|alice(?:/|\b))[A-Za-z0-9_.-]+/',data):
   findings.append((name,'non-placeholder home path'))
 for name,label in findings:print('REVIEW:',name,'—',label)
 print(f'Privacy scan: {count} files, {len(findings)} findings. Secret values are never printed.')
 return bool(findings)
if __name__=='__main__':sys.exit(main())
