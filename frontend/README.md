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

## Keyboard-only run-through (WCAG 2.2 AA, M7 exit criterion)

Perform against the live stack (`make dev`) with the mouse set aside:

1. `Tab` through the sign-in form: email → password → Continue; submit with
   `Enter`. Focus must be visible on every stop (3px outline).
2. Complete the verification-code step the same way.
3. In the procurement table, `Tab` to "Open moderation queue" and activate
   with `Enter` or `Space`.
4. In the queue, reach a "Moderate" button by keyboard; activate it.
5. In the decision view, move through the radio group with arrow keys,
   choose "Amend the score", `Tab` into the score and rationale fields,
   and submit with `Enter`. The rationale field must be reached and
   required.
6. Trigger an error (submit an amendment without a rationale): the message
   is announced via `role="alert"`.
7. "Back" controls and "Sign out" must be reachable and operable throughout.

Record the date and outcome here when performed:
- [ ] Keyboard run-through performed by a human reviewer (date, initials)
