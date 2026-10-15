2026-10-15 | Privacy & data screen at /settings/privacy (Settings tile) | export and delete live in one place, reachable from Settings.
2026-10-15 | Export is shown in a dialog (size, partial warning, per-service status) with copy-summary and copy-full-JSON via Clipboard | the app has no share/save plugin and new native plugins are out of scope.
2026-10-15 | Delete re-auths by password (field) plus a final confirm dialog; refresh_token variant exists in the repo only | simplest reliable re-auth; app has password login only.
2026-10-15 | On any success (200 deleted, 202 scheduled/partial) the app signs out, removes persisted settings keys, resets onboarding, shows a notice dialog and routes to /onboarding | server already revoked all sessions; 202 only changes the notice text.
2026-10-15 | ApiClient.delete gained an optional body (additive) | DELETE /v1/me requires a JSON body.
