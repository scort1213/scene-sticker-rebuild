#!/bin/bash
# Double-click to install or update the scene-sticker-rebuild skill for Codex.
cd "$(dirname "$0")" || exit 1
PY=python3
for v in python3.12 python3.11 python3.10; do command -v $v >/dev/null 2>&1 && PY=$v && break; done
"$PY" install.py "$@"
echo
read -r -p "Press Enter to close..." _
