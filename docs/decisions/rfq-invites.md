# rfq invite-only requests

2026-10-15 - Closes open item 1 of `docs/fixes/security-review-2026-10-g.md` (any user knowing a private request id could offer).

- New optional `invited_supplier_ids` (<= 50, each `[A-Za-z0-9_.:-]{1,64}`, de-duplicated) on `POST /v1/requests`; stored in table `request_invites` (migration 0006). Additive: omitted/empty = unchanged behaviour.
- Non-empty list = invite-only, independent of `visibility`. Invitees are matched against the gateway-verified `X-Supplier-Id` (already forwarded to rfq for admin-verified claims), never against the user id or any body field. Callers without a verified supplier id are never invitees.
- Buyer: always sees it and its offers. Invitees: see it in `scope=public` lists, detail, own offers, and can create offers. Everyone else: 404 on detail, offers list and offer create (identical to a missing id) and it is absent from lists. Previous "private + I already offered" access is superseded for invite-only requests.
- `invited_supplier_ids` is returned only in the buyer's own views (create, detail, `scope=mine`), never to suppliers.
- Invite list is fixed at creation (no edit endpoint). Gateway is a pure pass-through: no gateway change.
- Not changed: public requests; private requests without invites (owner + suppliers who offered).
