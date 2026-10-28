"""Gunicorn settings (read automatically when gunicorn starts in this folder).

Start with:  gunicorn config.wsgi
"""

import os

# Hosting platforms such as Railway tell the app which port to use.
bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"

# 2 workers × 2 threads fit comfortably in 512 MB–1 GB of RAM.
workers = int(os.environ.get("WEB_CONCURRENCY", "2"))
threads = int(os.environ.get("GUNICORN_THREADS", "2"))
timeout = 60

# Logs go to stdout/stderr, where the platform collects them.
accesslog = "-"
errorlog = "-"
