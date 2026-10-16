# Google Play Data Safety — draft answers (Factory Finder)

> **DRAFT, NOT LEGAL ADVICE.** Derived from code and docs: `services/gateway/src/ff_gateway/domain/privacy.py`, each service `privacy.py`, `docs/SECURITY.md`, `docs/OPS.md`, `docs/decisions/account-deletion.md`, `apps/mobile/pubspec.yaml`, `docs/STORE_LISTING.md` section 6. Re-verify against the release build (AndroidManifest, final dependency list) and the policy text before submitting. Where a third-party provider is only PLANNED/OPTIONAL, answer for the configuration you actually ship.

## 1. Data collection and security (top-level questions)
| Form field | Answer | Basis |
|---|---|---|
| Does the app collect or share user data? | Yes | accounts, messages, media, invoices |
| Is all data encrypted in transit? | Yes (requires HTTPS in release; verify TLS at the gateway) | SECURITY.md; confirm deploy |
| Can users request data deletion? | Yes | `DELETE /v1/me` (re-auth, fan-out erasure) |
| Deletion URL (web) | **[REQUIRED: public web page URL]** | in-app deletion screen does not exist yet (account-deletion.md "Known gaps") |
| Data export offered | Yes (`GET /v1/me/export`), optional on form | |
| Independent security review / committed to Play Families | No / Not applicable | not directed to children |
| Data sold | No | |

## 2. Data types
"Shared" below means transferred to a third party; processors acting on our behalf under contract are exempt from "sharing" per Play rules but should be listed in the policy. All third-party items are PLANNED/OPTIONAL (off by default).

| Play category / type | Collected | Shared | Optional | Purpose (Play codes) | Code basis |
|---|---|---|---|---|---|
| Personal info: Email address | Yes | No | Required | Account management; App functionality | `User.email` |
| Personal info: Name | Yes | No | Optional-ish (profile) | Account management; App functionality | `User.name` |
| Personal info: User IDs | Yes | No | Required | Account management; App functionality | gateway user id, `X-User-Id` |
| Personal info: Phone number | Yes | No | Optional | Account management; Communications | `User.phone` |
| Personal info: Address | No (destination city chosen, not street address) | - | - | - | `default_destination` |
| Personal info: Other (company name, role) | Yes | No | Optional | Account management | `User.company`, `role` |
| Financial info: Purchase history / other financial info | Yes (invoices and commissions: amount, status, payer/payee ids, public wallet address, tx id) | No (blockchain explorer/provider only if payments go live: public data) | Optional (only if user pays/receives) | App functionality | payments `InvoiceRow` |
| Financial info: Card or bank numbers | No | - | - | - | no card payments |
| Location (approximate/precise) | No | - | - | - | no device location; GPS EXIF stripped from images |
| Messages: Other in-app messages | Yes | No | Required for chat | App functionality | messaging service |
| Photos and videos: Photos | Yes | No | Optional | App functionality | media service (image_picker) |
| Files and docs | Yes (supplier verification documents; chat attachments) | No | Optional | App functionality; Fraud prevention, security | media/trust |
| Audio, contacts, calendar | No | - | - | - | |
| App activity: In-app search history | Yes (search queries/price history aggregated; per-user alerts and watchlists) | No | Optional | App functionality | notifications watchlists; sourcing history is not per viewer |
| App activity: Other user-generated content | Yes (listings, requests, offers, reviews, posts, comments, reports) | No | Optional | App functionality | rfq, feed, freight |
| App activity: Installed apps / other actions | No | - | - | - | |
| Web browsing | No | - | - | - | |
| App info and performance: Crash logs | No (no crash SDK) | - | - | - | pubspec has none |
| App info and performance: Diagnostics | Server-side request logs only (request id, route, status, duration, user id; no tokens/queries/bodies) | No | - | Fraud prevention, security; App functionality | OPS.md "Logs". Declare as collected "Diagnostics" if Play treats server logs as such; conservative answer is Yes |
| Device or other IDs | Yes, only if push enabled: device push token | Only FCM (Google) if enabled | Optional | App functionality | notifications devices; FCM PLANNED/OPTIONAL |
| Health and fitness | No | - | - | - | |
| Advertising ID / analytics | No | - | - | - | no analytics/ads SDK |

## 3. Fields needing the owner's decision
- Whether to answer "Shared: Yes" for FCM, LLM provider (assistant text, if enabled), tracking providers (tracking numbers), and USDT/TRON explorer. Default shipped config sends none of these, so answer No for the shipped build and update when enabled.
- Retention statement for the form's free text: see PRIVACY_POLICY.md section 6.
- Mobile app: confirm `google_fonts` loads only the bundled Cairo asset (no runtime font download to Google) before answering "no third-party sharing".
- Data deletion exceptions to disclose: financial/audit records (invoices, ledger, deals), supplier verification audit, anonymized abuse reports, counterparty message threads (own text blanked), deletion audit; backups per rotation.
- Account creation without Google/Facebook login: none present; no third-party sign-in data.
- Target audience: 18+; not designed for children.

## 4. Pre-submission checklist
1. Publish the Privacy Policy at a public URL and put it in the store listing.
2. Publish a web account-deletion page (and add the in-app screen).
3. Re-run the dependency list (`pubspec.lock`, Gradle) for SDKs and update section 2.
4. Have counsel approve PRIVACY_POLICY.md and TERMS_OF_SERVICE.md; fill all [BRACKETS].
