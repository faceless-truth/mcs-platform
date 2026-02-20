#!/bin/bash
# StatementHub — Production Start Script
# Runs with Gunicorn for 100+ concurrent users
#
# Usage:
#   ./start_production.sh          # Start in foreground
#   ./start_production.sh daemon    # Start as background daemon

set -e

# Activate virtual environment
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
source venv/bin/activate

# Run migrations
echo "Running database migrations..."
python manage.py migrate --noinput

# Collect static files
echo "Collecting static files..."
python manage.py collectstatic --noinput

# Start Gunicorn
echo "Starting Gunicorn (workers: auto, threads: 4)..."
if [ "$1" = "daemon" ]; then
    gunicorn config.wsgi:application \
        --config gunicorn.conf.py \
        --daemon \
        --pid /tmp/statementhub.pid
    echo "StatementHub started as daemon (PID: $(cat /tmp/statementhub.pid))"
else
    exec gunicorn config.wsgi:application \
        --config gunicorn.conf.py
fi
