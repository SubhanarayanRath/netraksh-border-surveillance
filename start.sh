#!/bin/bash
# NETRAKSH - Unified startup script for Render deployment
# Starts the background Edge pipeline and the FastAPI backend.

echo "Starting Edge Pipeline in the background..."
# We run the demo runner which polls for /demo/scenario changes.
# This allows video uploads via the frontend to trigger an edge restart.
python edge/demo_runner.py &

echo "Starting FastAPI Backend..."
# The port is supplied by Render via the $PORT environment variable.
uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8443}
