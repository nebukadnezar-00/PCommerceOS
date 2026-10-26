#!/bin/bash
# Runs the offline test suite (no network, temporary databases).
cd "$(dirname "$0")"
[ -x .venv/bin/pytest ] || .venv/bin/pip install -q -r requirements-dev.txt
exec .venv/bin/python -W ignore -m pytest -q "$@"
