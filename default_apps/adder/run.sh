#!/bin/sh

set -e

uv venv
uv pip install --upgrade syftbox
. .venv/bin/activate
python main.py
deactivate
