# Semsearch Console

Svelte 5, Tailwind CSS 4 and Vite. The API remains FastAPI/PostgreSQL. All fonts,
CSS and JavaScript are served from this app; only Google sign-in loads Google's
official script on the login screen.

## Development

```powershell
cd frontend
npm ci
npm run dev
```

Start the FastAPI backend on port 8000 separately. Vite proxies `/v1`, `/health`
and `/logo.png` to it. Hash routes preserve existing links and saved sessions.

## Validation and production

```powershell
npm run check
npm test
npm run build
```

The build writes `app/static/index.html` and content-addressed files in
`app/static/assets`. Keep these generated files together. The root HTML is
revalidated; versioned assets are cached for a year. The Dockerfile compiles the
same locked dependencies in a separate Node build stage; production runs Python
only. Keep old assets on the server through an active release transition.

## Async state

- `src/lib/api.js`: session generation, bounded timeouts, aborts, write
  deduplication, last-good table cache and per-view loaders.
- Components own their requests and dispose loaders on navigation. A stale
  transport response cannot update a destroyed or newer view.
- Navigation renders the selected screen without waiting for a catalog request.
  Catalog reads coalesce and cache for 30 seconds. Failed refreshes preserve data.
- Writes never retry automatically. A timed-out write directs the user to check
  the outcome before submitting again.
- Non-secret query/editor drafts stay in bounded memory and clear on logout.
  Passwords/API key values are not stored in drafts. Revealed keys clear after
  30 seconds, on navigation, page hide or tab backgrounding.

## Tests

Vitest covers reordered responses, disposal during reads, stale 401s after a new
login, switching session persistence, duplicate authentication/writes, timeouts,
catalog cache/error behavior, instant navigation and keyboard focus. Backend
tests verify build asset serving/cache headers and authentication no-store.
