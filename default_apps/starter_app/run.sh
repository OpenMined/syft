#!/bin/sh

set -e

uv venv
. .venv/bin/activate
python main.py
deactivate
