#!/usr/bin/env sh

set -e

# start Jupyter Lab in the background with output redirection
uv run jupyter lab --ip=0.0.0.0 --no-browser --allow-root --ServerApp.token="$JUPYTER_TOKEN" --notebook-dir=~/SyftBox/ >/proc/1/fd/1 2>/proc/1/fd/2 &

# start SyftBox client in foreground
exec uv run syftbox client --service
