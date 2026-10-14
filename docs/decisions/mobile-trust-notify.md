2026-10-14 | Trust v2 UI lives on the supplier screen as a card (confidence meter, flag chips, data gaps, history chart, report sheet); additive fields added to TrustScore with tolerant parsing | contract fields are additive/optional
2026-10-14 | Legacy fractional `confidence` (<=1.0 double, as in the old trust.json fixture) is scaled to 0-100 | older gateway builds returned 0-1
2026-10-14 | History chart is a CustomPaint line (no chart dependency); fewer than 2 points shows a text fallback | no new pub deps
2026-10-14 | Report sheet is offered only when logged in (guests get a sign-in snackbar); 429 and 401 map to dedicated messages; success is shown inside the sheet | contract needs X-User-Id, rate limit 5/h
2026-10-14 | Notification prefs screen at /notification-prefs (Profile tile); added ApiClient.put; alert types are the 5 Alert.rule values; timezone is a dropdown of common zones (+ current value) | no timezone package allowed
2026-10-14 | Empty digest email is simply omitted from PUT (contract has no way to clear it); quiet hours off sends clear_quiet_hours=true | NotificationPrefsUpdate shape
