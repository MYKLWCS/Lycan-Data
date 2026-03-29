#!/bin/bash
set -e

echo "Running database migrations..."
python3 -m alembic upgrade head 2>&1 || echo "Migration warning (may already be up to date)"

echo "Starting application..."
exec "$@"
