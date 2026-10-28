# Container image for the public demo on Railway (fake data only).
# See docs/DEPLOY-RAILWAY.md. The pilot on a Russian VPS will not use Docker.
#
# Everything that does not need the database happens here, at build time:
# pinned requirements, Tailwind CSS, compiled translations and collectstatic.
# Database steps (migrate, createcachetable, demo data) run in Railway's
# pre-deploy command: `python manage.py predeploy`.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=config.settings.railway \
    DJANGO_READ_DOT_ENV=false

# gettext: to compile the translations (.po -> .mo) during the build.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gettext \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Build-only values: the build has no database and no real secret. Nothing
# here is kept in the image's runtime environment.
RUN python scripts/tailwind.py build \
    && DJANGO_SECRET_KEY=build-only DEMO_MODE=true DATABASE_URL=sqlite:////tmp/build.sqlite3 \
       python manage.py compilemessages \
    && DJANGO_SECRET_KEY=build-only DEMO_MODE=true DATABASE_URL=sqlite:////tmp/build.sqlite3 \
       python manage.py collectstatic --noinput \
    && rm -rf bin /tmp/build.sqlite3

# Run as an unprivileged user.
RUN useradd --create-home app && chown -R app /app
USER app

# Port and worker count come from gunicorn.conf.py ($PORT, $WEB_CONCURRENCY).
CMD ["gunicorn", "config.wsgi"]
