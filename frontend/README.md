# TenderScore frontend

React 18 · TypeScript (strict) · Vite. Plain REST plus SSE for long-running
jobs. WCAG 2.2 AA is a hard requirement — semantic HTML, keyboard
navigation, axe-core checks in CI. British English in all UI strings.

## Layout

| Path | Purpose | Built in |
|---|---|---|
| `src/app/` | Routing and auth shell | M0 shell, M1+ |
| `src/features/` | Framework, submissions, scoring, moderation, admin | M3+ |
| `src/components/` | Design system (WCAG 2.2 AA) | M3+ |
| `src/api/` | Typed client generated from the backend OpenAPI schema | M1+ |
| `tests/` | Vitest + axe-core accessibility checks | M0+ |

## Running locally

From the repository root: `make dev` (Docker Compose) or, natively:

```sh
cd frontend
npm install
npm run dev
```

Checks: `npm run typecheck`, `npm test`.
