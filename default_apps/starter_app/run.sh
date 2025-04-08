#!/bin/sh

set -e

if [ ! -d .venv ]; then
    uv venv -p 3.12 .venv
fi
. .venv/bin/activate

echo "Running 'starter_app' with $(python3 --version) at '$(which python3)'"
uv run python3 main.py

deactivate
