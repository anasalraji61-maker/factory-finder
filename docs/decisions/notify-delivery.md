2026-10-14 | Push/email OFF by default (FF_NOTIFY_PUSH/FF_NOTIFY_EMAIL=off) | no provider = no deliveries enqueued; mock only for tests/dev.
2026-10-14 | Deliveries are separate rows with deterministic ids (hash of kind/channel/device/alert ids) | idempotent enqueue; alerts commit first so delivery failure never blocks alert creation.
2026-10-14 | Processing runs inline after evaluation (exceptions suppressed) plus the scheduler loop | no extra worker process; retries ride the existing loop.
2026-10-14 | Quiet hours defer push to window end without consuming an attempt; email digest ignores quiet hours | digest is sent only after 08:00 local anyway.
2026-10-14 | in_app channel is accepted in prefs but the inbox is never suppressed | inbox is the source of truth; hiding alerts would lose data.
2026-10-14 | Device cap counts active devices only; token already owned by the user may re-register at the cap | dedupe by token; dead tokens should not lock users out.
2026-10-14 | FCM JWT signing needs optional `cryptography` (extra `fcm`), imported lazily | keeps base install light; flow UNVERIFIED against live Google endpoints.
