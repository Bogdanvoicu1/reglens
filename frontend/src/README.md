# `frontend/src` — React SPA

Vite + React 18 + TypeScript + Tailwind v4 + TanStack Query. Two views behind a
slim nav rail: **Ask** (streaming grounded chat) and **Assess** (the compliance
assessment agent). Dark zinc + EU-blue theme.

## Entry & shell

- `main.tsx` — mounts the app. `App.tsx` — fetches runtime config (`/api/v1/config`), wires Supabase auth when configured, and switches between the chat and assess views.
- `types.ts` — shared API/response types.

## `lib/` — data & auth plumbing

| File | Role |
|---|---|
| `api.ts` | `fetch` wrapper that attaches the bearer token and maps errors to `ApiError`; guards against 401 reload loops |
| `auth.ts` | Token storage (`reglens.token` is the single source of truth read by the API client and the SSE streamers) + Supabase-aware `signOut` |
| `config.ts` | Fetches/caches `/api/v1/config`; decides Supabase login vs. local dev-token sign-in |
| `supabase.ts` | Lazily-created Supabase client (only when the backend reports a project) |
| `sse.ts` | Custom SSE-over-`fetch` parser (`streamSSE` / `createSSEBuffer`) — needed because `EventSource` can't send auth headers; `sse.test.ts` covers it |

## `hooks/`

- `useChatStream.ts` — drives the chat SSE (tokens, citations, refusal, done).
- `useAssessmentStream.ts` — drives the assessment SSE (stage events, clarification, report) with start/answer/reset.

## `components/`

**Auth & nav:** `TokenGate` (Supabase login *or* dev-token box, chosen from config), `NavRail` (Ask/Assess switch + sign-out).

**Ask:** `ChatPanel` (compose + stream), `AnswerView` (markdown answer with inline citation chips), `SourceList` (cited articles/recitals panel), `HistorySidebar`.

**Assess:** `AssessmentsView` (intake | live | saved orchestration + history), `AssessmentIntake` (description + sample + clarify toggle), `StageTimeline` (live per-stage status over the SSE), `ClarificationPanel` (one-round HITL questions), `ReportView` (executive summary, stat cards, obligation cards with gap badges + citations, remediation roadmap, authenticated `.md` download).

## Auth modes

The backend always verifies a JWT; the SPA only chooses the sign-in UI from
`/api/v1/config`. With a Supabase project configured it renders a real
email/password login and mirrors the access token into `reglens.token`
(refreshed via `onAuthStateChange`); without one it shows the dev-token box.
See the repo README's Authentication section.
