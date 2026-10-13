2026-10-13 | Live paths follow the OpenAPI contracts (`/v1/search`, `/v1/trust/suppliers/{id}`, `/v1/quotes/landed-cost`, rfq `scope=mine|public`) | The MVP guessed endpoints; contracts are the single source of truth.
2026-10-13 | Sort and supplier filter are applied client-side for live search | `/v1/search` has no sort or supplier_id params.
2026-10-13 | Tokens live in a `TokenStore` (in memory) shared by `ApiClient`; `authProvider` holds the `Me` user | Server-URL changes recreate ApiClient without losing the session.
2026-10-13 | Mock mode login accepts any credentials and sets the mock user `usr_mock` | Keeps "my requests" fixtures usable without a backend.
2026-10-13 | No category field in the create-request form or body | rfq `RequestCreate` has additionalProperties=false and no category; `RfqDraft.category` stays null.
2026-10-13 | Accept dialog shows a client-side commission estimate (3/2/4 % by kind, min 25 USD) then the server Deal | Matches rfq.yaml description; server value is authoritative.
2026-10-13 | Condition chips are any/new/used only | rfq `RequestCreate.condition` does not allow `refurbished`.
