# Vercel deployment (frontend only)

This repository is configured to publish the **React frontend** to Vercel as a static Vite site.
The FastAPI backend stays on a container host (Render, Fly, Railway, Cloud Run, etc.) because
it needs a long-lived Python process for the cached pipeline and SQLite/KV-backed reviews.

I cannot complete the publish step from here because no Vercel credentials are available in this
environment. Follow the steps below with your own Vercel account.

## 1. Frontend → Vercel

1. Push this repository to GitHub/GitLab/Bitbucket.
2. In Vercel, choose **Add New → Project** and import the repository **with the repository root as the root directory**.
3. Vercel will detect `vercel.json`:
   - Build command: `npm --prefix frontend install --include=dev && npm --prefix frontend run build`
   - Output directory: `frontend/dist`
   - SPA fallback rewrites are included, so `/review`, `/ledger`, etc. work on refresh.
4. Add the frontend environment variable:
   - `VITE_API_URL=https://your-api-host.example.com`
   - Use the public HTTPS URL of the backend; no trailing slash.
5. Deploy. Your UI will be available at `https://<project>.vercel.app`.

`frontend/vercel.json` is also included in case you prefer to set Vercel's **Root Directory** to
`frontend` instead of the repository root. Use one configuration approach, not both.

Preview deployments receive their own `*.vercel.app` URLs; the backend CORS configuration below
allows them automatically.

## 2. Backend → container host

Deploy the existing `Dockerfile` to your provider (Render Web Service, Fly App, Railway, etc.):

```bash
# Local equivalent
docker compose up --build -d
```

The container exposes port `8000` (or `$PORT` if your provider sets it) and serves:

- `/api/*` — JSON API
- `/docs` — OpenAPI docs
- `/api/health` — health check

## 3. Vercel KV for review outcomes

Serverless/static hosting has no persistent filesystem, so the backend uses Vercel KV (Upstash
Redis) when the following variables are set. Otherwise it falls back to local `data/review.db`.

1. In Vercel, create a **KV** store (Storage → Create Database → KV).
2. Open the store and copy its REST URL and token.
3. Set these on the **backend** host (not the frontend project):

| Variable | Value |
|---|---|
| `KV_REST_API_URL` | `https://…upstash.io` |
| `KV_REST_API_TOKEN` | the store's REST token |
| `API_CORS_ORIGINS` | `https://<project>.vercel.app` (plus your custom domain) |
| `CORS_ORIGIN_REGEX` | optional; defaults to `https://.*\.vercel\.app` |

Review outcomes and the append-only audit trail are stored under the `review:*` keys. The public
API is unchanged, so the UI works identically with SQLite or KV.

## 4. Verification

```bash
# Static frontend
curl -fsS https://<project>.vercel.app/ | head
curl -fsS https://<project>.vercel.app/review | head   # SPA fallback

# API on the separate host
curl -fsS https://your-api-host.example.com/api/health
curl -fsS https://your-api-host.example.com/api/overview
```

In the browser, confirm the disclaimer is visible and that setting a review outcome survives a
backend restart (this proves KV persistence).

## Notes and limitations

- Only the frontend runs on Vercel; the API is a separate service.
- The frontend Vite build injects `VITE_API_URL` at **build time**. Changing it requires a redeploy.
- If KV variables are missing on the backend, outcomes are stored in the container filesystem and
  may be lost when the container is replaced.
- Do not put Vercel tokens in `frontend/.env`; frontend variables are public by design.
