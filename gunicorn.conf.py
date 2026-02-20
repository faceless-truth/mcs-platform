"""
Gunicorn Configuration for StatementHub (MC&S Platform)
Optimised for up to 100 concurrent users.

Sizing rationale:
- 100 concurrent users with typical page load = ~50-80 simultaneous requests
- Workers = (2 × CPU cores) + 1 is the standard formula
- Threads per worker handle I/O-bound operations (DB queries, file generation)
- With 4 workers × 4 threads = 16 concurrent request handlers
- This comfortably handles 100 concurrent users with typical web traffic patterns
"""
import multiprocessing
import os

# ─── Binding ──────────────────────────────────────────────────────────────────
bind = os.environ.get("GUNICORN_BIND", "0.0.0.0:8000")

# ─── Workers ──────────────────────────────────────────────────────────────────
# Formula: (2 × CPU cores) + 1, minimum 4 for 100 concurrent users
workers = max(4, (2 * multiprocessing.cpu_count()) + 1)

# Use gthread worker class for Django (handles I/O-bound work well)
worker_class = "gthread"

# Threads per worker — handles concurrent requests within each worker
threads = 4

# ─── Timeouts ─────────────────────────────────────────────────────────────────
# Document generation (PDF conversion via LibreOffice) can take up to 2 minutes
timeout = 180
graceful_timeout = 30
keepalive = 5

# ─── Request Limits ───────────────────────────────────────────────────────────
# Max simultaneous clients (should exceed expected concurrent users)
worker_connections = 200

# Restart workers after this many requests to prevent memory leaks
max_requests = 1000
max_requests_jitter = 50

# ─── Logging ──────────────────────────────────────────────────────────────────
accesslog = os.environ.get("GUNICORN_ACCESS_LOG", "-")
errorlog = os.environ.get("GUNICORN_ERROR_LOG", "-")
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")

# ─── Process Naming ───────────────────────────────────────────────────────────
proc_name = "statementhub"

# ─── Preloading ───────────────────────────────────────────────────────────────
# Preload the application to share memory between workers (saves ~30% RAM)
preload_app = True

# ─── Temporary Files ──────────────────────────────────────────────────────────
# Use /dev/shm for worker heartbeat files (faster than disk)
tmp_upload_dir = None
worker_tmp_dir = "/dev/shm"
