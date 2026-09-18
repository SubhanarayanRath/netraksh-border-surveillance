# NETRAKSH — Deploying to Render

This is the actual walkthrough for the deployment this project is configured for
(`Dockerfile`, `render.yaml`, `requirements-backend.txt`). It deploys the command-center
backend + frontend (one container, one process, matching how this app has always run
locally) with a real managed Postgres database. It does **not** deploy the edge pipeline —
that runs on a camera-side device in the real architecture, not on Render; see
"What this does NOT deploy" below.

## Supported Deployment Matrix

The application supports multiple deployment environments using the exact same codebase. The frontend remains agnostic and selects the backend via `VITE_BACKEND_URL`, while the backend relies on `DATABASE_URL` for PostgreSQL.

### SUPPORTED NOW

**A. Firebase Hosting → Render → Supabase PostgreSQL**
- Frontend is hosted on Firebase (`https://netraksh-35030.web.app`).
- Communicates with the Render FastAPI backend (`https://netraksh.onrender.com`).
- Render connects to Supabase PostgreSQL.

**B. Vercel → Render → Supabase PostgreSQL**
- Frontend is hosted on Vercel (`https://netraksh.vercel.app`).
- Communicates with the Render FastAPI backend (`https://netraksh.onrender.com`).
- Render connects to Supabase PostgreSQL.

**C. Local Frontend → Local/Render Backend → PostgreSQL**
- Frontend running locally (`http://localhost:5173`).
- Connects to a local backend (`http://localhost:8443`) or remote Render backend.
- Backend connects to SQLite or Supabase PostgreSQL.

### FUTURE / NOT IMPLEMENTED

**D. Firebase Native Stack (Firebase-Only)**
- Firebase Hosting → Firebase Auth → Firestore / Realtime Database.
- *Status:* **NOT CURRENTLY IMPLEMENTED**. 
- *Note:* If built in the future, this should be treated as a separate backend/data implementation profile, not interleaved within the current standard React logic.

## Prerequisites

- A GitHub repository containing this project (push it there first if it isn't already).
- A Render account (render.com — free to create, no credit card required for the free tier
  used here).

## Steps

1. **Push this repo to GitHub** if you haven't already:
   ```bash
   git remote add origin https://github.com/<your-username>/<your-repo>.git
   git push -u origin master
   ```

2. **On Render: New → Blueprint.** Connect your GitHub account if this is your first time,
   then select this repository. Render will detect `render.yaml` at the repo root
   automatically and show you the two resources it defines:
   - `netraksh` — a web service, built from `Dockerfile`, on the free plan
   - `netraksh-db` — a managed Postgres database, on the free plan

3. **Click Apply.** Render provisions the database first, then builds and deploys the web
   service. The first build takes a few minutes (it builds the frontend, then the Python
   image). Watch the build logs in the Render dashboard for the same messages you'd see
   running this locally (`Database tables created/verified`, `Command Center ready...`).

4. **Retrieve the generated admin password.** `render.yaml` has Render generate real random
   values for `SECRET_KEY`, `ADMIN_PASSWORD`, `INITIAL_OPERATOR_PASSWORD`, and
   `INITIAL_AUDITOR_PASSWORD` at deploy time — never the `CHANGE_ME_*` placeholders
   `backend/config.py` defaults to locally, and never committed anywhere. To log in:
   Render dashboard → the `netraksh` service → **Environment** tab → find `ADMIN_PASSWORD`
   → reveal it. Username is `admin`. 
   
   *(Note: These are seed-time values only. Existing users in Supabase PostgreSQL remain the source of truth.)*

5. **Open the live URL.** Render assigns one automatically
   (`https://netraksh-<random>.onrender.com`, shown at the top of the service page). Every
   part of the frontend that used to hardcode `localhost:8443` was fixed to derive its
   backend URL from `window.location` at runtime (see `docs/ARCHITECTURE.md`), so this
   works with zero further configuration — the same build that runs on `localhost:8443`
   runs correctly here.

## What this does NOT deploy

- **The edge pipeline** (`edge/`) — YOLOv8n detection, the Reliability Engine, evidence
  encryption/signing, the offline sync queue. That code runs on a camera-side machine in
  the real architecture and was deliberately excluded from this container (see the
  Dockerfile's own comments and `requirements-backend.txt`) — installing
  `ultralytics`/`opencv`/`easyocr`/`retina-face` into a service that never imports any of
  it would multiply build time and image size for nothing. To see real edge-generated
  events on the live deployment, either run `edge/main.py` locally pointed at
  `BACKEND_URL=https://<your-render-url>`, or POST a synthetic event directly to
  `POST /events` (see any of this project's own verification steps in
  `docs/ARCHITECTURE.md` for the exact payload shape) to demo the dashboard live.
- **A real blockchain network.** `BLOCKCHAIN_MODE` stays `mock` — Fabric needs
  Docker/WSL2, unavailable on the dev machine this was built on, and out of scope for a
  free web-service deploy target too.

## Known limitation: unverified against a real Postgres instance

Docker was never available on the machine this was built on, so the Postgres code path
(`psycopg2-binary`, the `postgres://` → `postgresql://` URL-scheme fix in
`backend/config.py`, `pool_pre_ping`/`pool_size` engine settings in
`backend/database/session.py`) was written and reasoned through carefully but **could not
be exercised against a real running Postgres server before this deployment** — every
verification in this project up to now has been against real SQLite. The schema-creation
and migration logic (`init_db()`, `_migrate_add_missing_columns()`) is written to be
database-agnostic via SQLAlchemy's `inspect()`, not SQLite-specific, but "written to be"
and "verified to be" are different claims — this is the first time it's actually true.

