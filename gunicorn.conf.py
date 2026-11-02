"""Gunicorn settings (read automatically when gunicorn starts in this folder).

Start with:  gunicorn config.wsgi
"""

import os

# Hosting platforms such as Railway tell the app which port to use. On the
# pilot VPS, nginx talks to gunicorn through a local socket instead:
# GUNICORN_BIND=unix:/run/dorm-laundry/gunicorn.sock (deploy/systemd/).
bind = os.environ.get("GUNICORN_BIND") or f"0.0.0.0:{os.environ.get('PORT', '8000')}"

# 2 workers × 2 threads fit comfortably in 512 MB–1 GB of RAM.
workers = int(os.environ.get("WEB_CONCURRENCY", "2"))
threads = int(os.environ.get("GUNICORN_THREADS", "2"))
timeout = 60

# Logs go to stdout/stderr, where the platform collects them.
accesslog = "-"
errorlog = "-"
