#!/usr/bin/env python3
"""Prepare a NEW private runtime; never overwrite an existing Jarvis installation."""
from pathlib import Path
import shutil
import sys
ROOT=Path(__file__).resolve().parents[1]
HOME=Path.home()/'.openjarvis'
def main():
 target=HOME/'runtime'
 if target.exists():sys.exit('Existing Jarvis runtime found. Nothing changed. Use a separate Mac/user or inspect the export manually.')
 target.mkdir(parents=True,mode=0o700)
 shutil.copytree(ROOT/'runtime',target,dirs_exist_ok=True)
 shutil.copytree(ROOT/'vendor/OpenJarvis',target/'OpenJarvis',dirs_exist_ok=True)
 shutil.copytree(ROOT/'runtime/personal-ui',target/'OpenJarvis/src/openjarvis/server/static',dirs_exist_ok=True)
 shutil.copytree(ROOT/'galaxy',target/'galaxy',dirs_exist_ok=True)
 shutil.copy2(ROOT/'config/jarvis.example.toml',HOME/'openjarvis-personal.toml')
 (HOME/'openjarvis-personal.toml').chmod(0o600)
 (HOME/'logs').mkdir(mode=0o700,exist_ok=True)
 (HOME/'chatgpt-subscription').mkdir(mode=0o700,exist_ok=True)
 import json
 p=HOME/'chatgpt-subscription/policy.json';p.write_text(json.dumps({'enabled':True,'mode':'openrouter-free','model':'openrouter/free'}));p.chmod(0o600)
 print('Prepared private runtime. Next follow docs/SETUP.md to install dependencies and enter your own key locally.')
if __name__=='__main__':main()
