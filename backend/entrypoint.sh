#!/bin/sh
set -e

alembic upgrade head
python -m kb.loader || echo "WARNING: the knowledge base could not be loaded, starting with the articles already stored" >&2
exec uvicorn main:app --host 0.0.0.0 --port 8000
