# Supabase setup

RegLens uses Supabase as its **identity provider only**. Supabase issues and
manages user sessions; the API verifies each request's JWT locally against the
project's JWKS endpoint (asymmetric keys, no per-request call back to Supabase).

All application data — users, tenants, conversations, the regulation corpus and
its embeddings, assessments — lives in RegLens's **own Postgres database**
(managed by Railway in production, or the local `pgvector` container in
development). It does **not** live in Supabase's database.

That split matters for two things this guide does *not* cover, on purpose:

- **No tables are created in Supabase.** The schema below runs against
  RegLens's Postgres via Alembic, not against the Supabase database.
- **No Supabase Row Level Security policies are needed.** RegLens never queries
  Supabase's database from the app, so there is nothing there to protect with
  RLS. Tenant isolation is enforced in the application's repository layer:
  every query is scoped to the tenant derived from the verified JWT subject.

## 1. Create the project

1. Sign in at <https://supabase.com> and create a new project.
2. Choose a region close to where the API runs (lower auth-verification
   latency, though JWKS is cached so this is minor).
3. Note the project reference (the `<ref>` in `https://<ref>.supabase.co`).

## 2. Get the keys

Project Settings → API:

| Value                                                                | Where it is used                                                      | Public?                            |
| ----------------------------------------------------------------------| -----------------------------------------------------------------------| ------------------------------------|
| Project URL (`https://<ref>.supabase.co`)                            | Frontend `VITE_SUPABASE_URL`                                          | Yes                                |
| `anon` / publishable key                                             | Frontend `VITE_SUPABASE_ANON_KEY`                                     | **Yes** — designed for the browser |
| JWKS URL (`https://<ref>.supabase.co/auth/v1/.well-known/jwks.json`) | Backend `REGLENS_SUPABASE_JWKS_URL`                                   | Yes                                |
| Issuer (`https://<ref>.supabase.co/auth/v1`)                         | Backend `REGLENS_SUPABASE_ISSUER` (optional)                          | Yes                                |
| `service_role` key                                                   | **Not used by RegLens. Never put it in any env file or the browser.** | No — full DB access                |

RegLens needs no service-role key: it never talks to Supabase's database or
admin API. If you see it asked for anywhere in this project, that is a bug.

## 3. Configure auth

1. Authentication → Providers → Email: enable **Email** sign-in.
2. To let users self-register from the SPA login page, enable **Allow new
   users to sign up**. Otherwise create users from the dashboard
   (Authentication → Users → Add user).
3. (Optional) Authentication → URL Configuration → add your deployed SPA origin
   to the redirect allow-list if you later enable email confirmation or OAuth.

### Attaching users to a shared workspace (optional)

By default a user's first authenticated request just-in-time provisions a
personal tenant. To place a user into an existing workspace instead, set an
`app_metadata.tenant_id` claim on the user (Authentication → Users → user →
edit `app_metadata`). The API reads that claim and binds the user to that
tenant.

## 4. The database schema (RegLens Postgres, not Supabase)

The schema is defined as Alembic migrations under `backend/alembic/versions/`.
Apply them against whichever Postgres RegLens uses. The baseline migration
enables `pgvector` itself (`CREATE EXTENSION IF NOT EXISTS vector`), so the
only requirement is a Postgres that allows that extension (the
`pgvector/pgvector` image locally; Railway's Postgres supports it).

```bash
cd backend
# DATABASE_URL points at the target Postgres (local container or Railway)
uv run alembic upgrade head
```

In production this runs automatically on every backend deploy — see the
`startCommand` in `backend/railway.json`.

To inspect or hand-apply the SQL without Alembic, render it:

```bash
cd backend
uv run alembic upgrade head --sql > schema.sql   # offline SQL for review
```

## 5. Point local vs production at the project

The same Supabase project can serve both environments; only the env files
differ in *where* they live.

**Local**

- `backend/.env`: `REGLENS_SUPABASE_JWKS_URL` (and optionally
  `REGLENS_SUPABASE_ISSUER`).
- `frontend/.env`: `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`.

**Production (Railway)** — set the same variables as service variables; see
[DEPLOY_RAILWAY.md](DEPLOY_RAILWAY.md).

## 6. Verify

1. Start the stack and open the SPA.
2. Sign up or sign in on the login page.
3. Ask a question. A `200` streamed answer proves the full chain: supabase-js
   minted a token, the API verified it against the JWKS endpoint, provisioned
   your tenant, and served a grounded answer from RegLens's own Postgres.
4. An unauthenticated `curl` to a protected route returns `401`:

   ```bash
   curl -s -o /dev/null -w "%{http_code}\n" https://<api-host>/api/v1/corpora
   # 401
   ```
