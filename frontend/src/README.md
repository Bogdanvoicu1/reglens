# `frontend/src` — React SPA

Vite + React 18 + TypeScript + Tailwind v4 + TanStack Query. Two views behind a
slim nav rail: **Ask** (streaming grounded chat) and **Assess** (the compliance
assessment agent). Dark zinc + EU-blue theme.

## Entry & shell

- `main.tsx` — mounts the app. `App.tsx` — gates on the Supabase session (`useSession`) and switches between the chat and assess views once signed in.
- `types.ts` — shared API/response types.

## `lib/` — data & auth plumbing

| File | Role |
|---|---|
| `env.ts` | Reads build-time Supabase config (`VITE_SUPABASE_URL` / `VITE_SUPABASE_ANON_KEY`); fails fast if missing |
| `supabase.ts` | The app's single Supabase client, created from `env` |
| `auth.ts` | `getAccessToken()` (read fresh from supabase-js) + `signOut()`; the app never stores the token itself |
| `api.ts` | `fetch` wrapper that attaches the bearer token and maps errors to `ApiError` |
| `sse.ts` | Custom SSE-over-`fetch` parser (`streamSSE` / `createSSEBuffer`) — needed because `EventSource` can't send auth headers; `sse.test.ts` covers it |

## `hooks/`

- `useSession.ts` — subscribes to the Supabase session (`undefined` while resolving, `null` signed out, else the session).
- `useChatStream.ts` — drives the chat SSE (tokens, citations, refusal, done).
- `useAssessmentStream.ts` — drives the assessment SSE (stage events, clarification, report) with start/answer/reset.

## `components/`

**Auth & nav:** `LoginPage` (Supabase email/password sign-in + product overview), `NavRail` (Ask/Assess switch + sign-out).

**Ask:** `ChatPanel` (compose + stream), `AnswerView` (markdown answer with inline citation chips), `SourceList` (cited articles/recitals panel), `HistorySidebar`.

**Assess:** `AssessmentsView` (intake | live | saved orchestration + history), `AssessmentIntake` (description + sample + clarify toggle), `StageTimeline` (live per-stage status over the SSE), `ClarificationPanel` (one-round HITL questions), `ReportView` (executive summary, stat cards, obligation cards with gap badges + citations, remediation roadmap, authenticated `.md` download).

## Auth

Supabase email/password. supabase-js owns the session (persisted and
auto-refreshed); `useSession` reflects it and `api.ts` reads the current access
token on demand for the bearer header. The backend verifies that token locally
against the project's JWKS. Configure the project in `frontend/.env`
(`VITE_SUPABASE_*`); see the repo README's Authentication section.
