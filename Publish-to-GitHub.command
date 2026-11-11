#!/bin/zsh
set -eu
cd "${0:A:h}"
python3 scripts/publish.py
print '\nPress Return to close.'
read
