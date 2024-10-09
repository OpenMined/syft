#!/bin/bash
uv run uvicorn syftbox.server.server:app --host 0.0.0.0 --reload  --port 5001 --reload-dir ./syftbox
