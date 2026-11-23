#!/bin/bash
cd "$(dirname "$0")"
. venv/bin/activate
echo "Starting Emotion Engine..."
venv/bin/python core.py
exec bash
