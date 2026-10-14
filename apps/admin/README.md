# apps/admin

Small admin console (plain HTML + vanilla JS, no build step, no CDN). Arabic-first RTL with an English toggle. Tabs: **Supplier claims** (approve/reject pending), **Demand drafts** (filter by status, see the source post, edit text then approve, reject, mark published, record outcome, daily quota), **Overview** (counts).

It talks only to the gateway: `/v1/admin/supplier-claims*`, `/v1/admin/demand/*`, `/v1/admin/overview` with header `X-Admin-Token`.

## Run
- Same origin (recommended): start the gateway with `FF_GATEWAY_ADMIN_TOKEN=<secret> FF_GATEWAY_SERVE_ADMIN=true` and open `http://localhost:8000/admin/`. Leave the gateway URL empty at login.
- Separate static host (`python -m http.server -d apps/admin 8200`): list that origin in `FF_GATEWAY_CORS_ORIGINS='["http://localhost:8200"]'` and enter the gateway URL at login (or edit `config.js`). CORS stays closed by default.

## Security
- Token is kept in `sessionStorage` only (cleared on sign-out / tab close), never in localStorage, never logged, sent only in `X-Admin-Token`.
- All rendered text uses `textContent`; no `innerHTML`. CSP meta tag: scripts/styles from self only. Post URLs are shown as text, never as links.
- Serve over HTTPS outside localhost; the admin token is a shared secret.
