# Deployment guide

The application deploys as **one process**: FastAPI serves the JSON API under `/api` and the
built React SPA (including client-side routes) from the same origin. No separate web server is
required for a basic deployment; put a reverse proxy in front for TLS/hosting.

## Prerequisites

```bash
pip install -r requirements.txt
npm --prefix frontend install
# Data is generated once; the container does this automatically.
python -m src.generate_data
```

## Option 1 — Single-process production server (simplest)

```bash
make serve                            # macOS/Linux: builds frontend + uvicorn
powershell -File scripts/serve.ps1    # Windows
```

Open <http://localhost:8000>. API docs are at <http://localhost:8000/docs> and the health check
at <http://localhost:8000/api/health>.

The SPA output is read from `deployment.static_dir` in `config.yaml` (`frontend/dist`). If it
has not been built, the API still runs and `/` returns a short JSON hint instead of failing.

## Option 2 — Docker / Compose

```bash
docker compose up --build -d
docker compose logs -f app
docker compose down
```

The multi-stage `Dockerfile` builds the frontend with Node, then copies `frontend/dist` into a
Python 3.11 runtime, generates the synthetic data, and starts uvicorn on `$PORT` (default 8000).
Review outcomes are stored at `REVIEW_DB_PATH=/app/state/review.db`, which Compose persists in the
`review-state` volume. CSV inputs are baked into the image, so the volume only holds review state.

## Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `REVIEW_DB_PATH` | Location of `review.db` (SQLite) for outcomes and audit trail | `data/review.db` from `config.yaml` |
| `PORT` | Listen port used by the container CMD | `8000` |
| `VITE_API_URL` | Frontend API base URL; only needed when the SPA is served separately | `http://localhost:8000` |
| `KV_REST_API_URL` / `KV_REST_API_TOKEN` | Enables Vercel KV (Upstash) storage for review outcomes and audit trail | unset (SQLite) |
| `API_CORS_ORIGINS` | Comma-separated extra allowed origins for the API | localhost only |
| `CORS_ORIGIN_REGEX` | Regex for allowed origins; defaults to Vercel preview domains | `https://.*\.vercel\.app` |

For a split deployment (Vite/object storage plus API), set `VITE_API_URL` before building the
frontend and keep the API's CORS origins in `api/main.py` in sync with your domain.

## Reverse proxy (nginx example)

```nginx
server {
    listen 80;
    server_name example.com;
    client_max_body_size 2m;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Terminate TLS with your certificate manager (e.g. certbot). The app itself is stateless apart
from `review.db`, so multiple workers are safe only if they share that SQLite file or you switch
to a managed database.

## Cloud platforms (Render / Fly / Railway / similar)

Use the included `Dockerfile` as the container image, expose/port-map `8000` (or let `$PORT`
select it), and attach a persistent volume to `/app/state` so `review.db` survives deploys. Set
`REVIEW_DB_PATH=/app/state/review.db`. A health check can target `/api/health`.

## Verification after deployment

```bash
curl -fsS http://localhost:8000/api/health
curl -fsS http://localhost:8000/api/overview
curl -fsS http://localhost:8000/review   # SPA fallback returns index.html
```

Then open the root URL and confirm the flag disclaimer is visible. Review flags are unusual
patterns requiring human judgement, not fraud determinations.

## Operational notes

- The dataset is synthetic and deterministic; regenerate it only when intentionally refreshing a deployment.
- `POST /api/reload` re-runs the pipeline from the current CSV files without a restart.
- Generated reports are written to `reports/` inside the process filesystem; add a volume if you need them persisted across deploys.
- Keep the disclaimer in place in every UI surface.
