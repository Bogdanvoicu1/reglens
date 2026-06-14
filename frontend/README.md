# RegLens frontend

The RegLens single-page app: a Vite + React 19 + TypeScript SPA with two views
behind a slim nav rail — **Ask** (streaming grounded chat with inline citation
chips and a source panel) and **Assess** (the compliance assessment agent:
intake, a live per-stage timeline, one-round clarification, and the cited
readiness report). Tailwind v4 styling, TanStack Query for data, supabase-js for
auth.

The application code and its structure are documented in
[`src/README.md`](src/README.md). This file covers running and shipping the app.

## Develop

```bash
cp .env.example .env     # add your Supabase URL + anon key (both browser-safe)
npm install
npm run dev              # http://localhost:5173, proxying /api to the backend
```

| Script | Purpose |
|---|---|
| `npm run dev` | Vite dev server with HMR |
| `npm run build` | Type-check (`tsc -b`) then production build to `dist/` |
| `npm run preview` | Serve the production build locally |
| `npm run lint` | ESLint over the whole tree |

## Configuration

Two build-time variables, both safe to expose to the browser (never the
service-role key) — see `.env.example`:

- `VITE_SUPABASE_URL` — your Supabase project URL
- `VITE_SUPABASE_ANON_KEY` — the publishable/anon key

supabase-js owns the session (persisted + auto-refreshed); the API client reads
the current access token on demand for the bearer header. The backend verifies
that token against the project's JWKS. See the repo README's Authentication
section.

## Production image

The `Dockerfile` builds the SPA and serves it with nginx. Because Vite inlines
`VITE_*` at build time, the Supabase config is passed as build args (the root
`docker-compose` wires this from `frontend/.env`). At container start,
`docker-entrypoint.sh` renders `nginx.conf.template` so the `/api` upstream is
configurable per environment; `railway.json` carries the Railway deploy config.
See [`docs/DEPLOY_RAILWAY.md`](../docs/DEPLOY_RAILWAY.md).
