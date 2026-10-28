# Deploying the public demo on Railway

A step-by-step guide for someone who has never used Railway. It puts the
**demo** (fake data only) online at a Railway address such as
`https://dorm-laundry-demo.up.railway.app`, so the administration can try it
on their phones.

> **Read this first**
>
> - Railway hosts **outside Russia**. The demo may be **unreachable from some
>   Russian networks**. The dorm network checklist at the end decides whether
>   it can be shown to the administration.
> - The demo must **never hold real resident data**: no real names, rooms,
>   student codes or payments. The app refuses to start on Railway unless
>   `DEMO_MODE=true`, and every page shows a «Демо» banner.
> - The pilot with real data goes on Russian hosting instead (see
>   `docs/plans/admin-and-payments.md`, "Deployment").

Railway's dashboard changes from time to time. If a button has a slightly
different name, look for the closest match; the **check** after each section
tells you whether you got there.

## What the repository already contains

| File | What Railway does with it |
|---|---|
| `Dockerfile` | Railway finds it and builds the app with it: Python packages, CSS, translations and static files. |
| `gunicorn.conf.py` | The web server listens on the port Railway gives (`PORT`). |
| `config/settings/railway.py` | Settings for Railway (chosen by the Dockerfile). Adds the Railway address to the allowed hosts. |
| `manage.py predeploy` | Run before every release: updates the database, creates the cache table and, the first time, the demo data. |

Railway's old configuration file (`railway.json`) is **not** used: Railway has
deprecated it, so the two settings it would hold are typed into the dashboard
in section 5.

## 1. Account and a spending limit (do this first)

1. Sign up at <https://railway.com> (signing in with GitHub is easiest).
2. Choose a plan. The free tier has very little memory for an app plus a
   database; the **Hobby** plan ($5 a month, which includes $5 of usage) is
   enough for this demo. Prices change: check Railway's pricing page.
3. Open the **Usage** page of your workspace and click **Set Usage Limits**:
   - **Custom email alert**: for example $5. You get e-mails at 75%, 90% and
     100%; nothing stops.
   - **Hard limit**: for example $10 (the minimum). When reached, Railway
     takes the demo **offline** so you are never charged more.

**Check:** the Usage page shows your alert and your hard limit.

## 2. Create the project from GitHub

1. In the dashboard: **New Project** → **Deploy from GitHub repo**.
2. If asked, allow Railway to access your GitHub account and choose the
   `dorm-laundry` repository.
3. Railway creates a service for the app and starts a first build. **The
   first deploy is expected to fail**: the database and settings are not
   there yet.

**Check:** the project canvas shows one service named after the repository,
and its build log mentions the **Dockerfile**.

## 3. Add PostgreSQL

1. On the project canvas: **Create** (or **+ New**) → **Database** →
   **PostgreSQL**.
2. Wait until the PostgreSQL service shows as running.

**Check:** the canvas now shows two services: the app and **Postgres**.

## 4. Settings (environment variables) for the app

Open the **app** service (not Postgres) → **Variables**. Add these, one per
line (the **Raw Editor** lets you paste them all at once):

| Variable | Value | Why |
|---|---|---|
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` | Connects to the database. Type it exactly like this: Railway fills in the real address. If your database service has another name, use that name instead of `Postgres`. |
| `DJANGO_SECRET_KEY` | a long random text (see below) | Signs logins. Keep it secret. |
| `DEMO_MODE` | `true` | Demo banner, no search engines. **Must** be `true` on Railway. |
| `SEED_DEMO_STAFF_PASSWORD` | a password you choose | Password of the demo accounts `admin` and `manager`. The default from the README is refused. |
| `SEED_DEMO_RESIDENT_PIN` | 6 digits you choose, not `123456` | PIN of the demo residents D0001 … D0020. |
| `PORT` | `8080` | The port the app listens on (makes section 6 predictable). |

Generate the secret key on your own computer:

```bash
python -c "import secrets; print(secrets.token_urlsafe(50))"
```

Do **not** set `PILOT_READY`. You never need `RAILWAY_PUBLIC_DOMAIN`
(Railway sets it) or `DJANGO_SETTINGS_MODULE` (the Dockerfile sets it).

Write the demo passwords down somewhere private: you will share them with the
people testing the demo, and changing them later is a manual step (section 8).

**Check:** the Variables tab lists the six variables; `DATABASE_URL` shows a
resolved value when you hover or reveal it.

## 5. Pre-deploy command and health check

Still in the app service → **Settings** → the **Deploy** section:

1. **Pre-deploy Command**: `python manage.py predeploy`
   - Leave the timeout at its default, or set 300 seconds.
2. **Healthcheck Path**: `/healthz`
3. Leave **Start Command** empty: the Dockerfile already starts the app.

**Check:** both fields show your values after you leave the page and come back.

## 6. Give the demo an address

App service → **Settings** → **Networking** → **Public Networking** →
**Generate Domain**. If Railway asks for a port, enter `8080`.

**Check:** a domain like `something.up.railway.app` appears. Copy it.

## 7. Deploy

1. Deploy the latest version: in the app service, open **Deployments** and
   use **Redeploy** on the latest deployment (or push a commit to `main`).
2. Watch the logs of the new deployment:
   - **Build**: ends without errors (it compiles CSS and translations).
   - **Pre-deploy**: ends with `Pre-deploy steps done.` and, the first time,
     `Demo data ready for “Общежитие № 1”.`
   - **Deploy**: the health check on `/healthz` passes and the deployment
     becomes **Active**.

**Check:**

1. Open `https://<your-domain>/healthz`: it shows `{"status": "ok"}`.
2. Open `https://<your-domain>/`: the yellow banner «Демо: все имена и данные
   здесь вымышленные» is at the top and the login page is in Russian.
3. Log in as `admin` with `SEED_DEMO_STAFF_PASSWORD`: you see the resident
   list. Log in as student code `D0001` with `SEED_DEMO_RESIDENT_PIN`: you see
   the booking grid.

## 8. Demo data

- The demo data is created **automatically** by the first pre-deploy. Every
  later deploy runs it again and **changes nothing** once the demo exists, so
  what testers did stays.
- To run it by hand (also safe to repeat), use Railway's command-line tool:

  ```bash
  railway login
  railway link            # choose the project and the app service
  railway ssh -- python manage.py seed_demo
  ```

  `railway ssh` runs the command **inside** the deployed app, where the
  private database is reachable. (`railway run` runs on your own computer and
  cannot reach it.) The first time, the tool asks you to register an SSH key.
- **Changing a demo password later:** the variables are only used when the
  demo data is first created. To change a password afterwards:
  `railway ssh` then `python manage.py changepassword admin` (and `manager`).
- **Starting over with fresh demo data:** delete the Postgres service and add
  a new one (sections 3 and 4: update `DATABASE_URL` if the name changed),
  then redeploy. All demo data is lost; it is all fake.

**Check:** the resident list shows about 21 residents, two of them in debt.

## 9. Everyday tasks

- **Deploy a new version:** pushing to `main` deploys automatically if the
  service is connected to `main` (app service → **Settings** → **Source**).
  Otherwise use **Redeploy** as in section 7.
- **Read the logs:** app service → **Deployments** → a deployment → **View
  logs** (build, pre-deploy and runtime logs). Or `railway logs`.
- **Check the costs:** the workspace **Usage** page.
- **If the hard limit is reached** the demo goes offline. Raise or remove the
  limit, then redeploy.

## 10. Test from the dormitory network

Follow the "Dorm network checklist" in `docs/plans/admin-and-payments.md` on
2–3 phones over the dorm Wi-Fi **without VPN**, then on mobile data. Report
whether the site opens at all: that decides if this Railway demo can be shown
to the administration.

## 11. Tear down

When the demo is no longer needed:

1. Project → **Settings** → the danger zone at the bottom → **Delete
   project**, and confirm. Or from the command line:
   `railway delete --project <project-name>`.
2. This permanently deletes the app, the database and all (fake) data.

**Check:** the project is gone from the dashboard and the address no longer
opens.

## Troubleshooting

| What you see | Likely cause and fix |
|---|---|
| Build fails | Read the build log. A failing step names the cause (e.g. a typo in a template). The same build runs in GitHub CI ("Demo image" job). |
| Pre-deploy fails with "Set SEED_DEMO_STAFF_PASSWORD …" | Section 4: set both demo passwords to your own values. |
| Logs say "Refusing to start: the Railway demo must run with DEMO_MODE=true" | Section 4: set `DEMO_MODE` to `true`. |
| Health check fails | Check `DATABASE_URL` (section 4) and the runtime logs. `/healthz` returns 503 when the database cannot be reached. |
| "Bad Request (400)" in the browser | The address is not the one Railway generated. Use the domain from section 6; for a custom domain, add it to `DJANGO_ALLOWED_HOSTS` and `https://…` to `DJANGO_CSRF_TRUSTED_ORIGINS`. |
| Login says the password is wrong | The demo passwords are the values the variables had when the demo was first created (section 8). |
