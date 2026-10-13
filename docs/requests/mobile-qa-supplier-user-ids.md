# mobile-qa -> messaging/gateway: suppliers are not users

The app opens a chat from a listing/supplier page and only knows the catalog supplier id (`sup_cn_018`).
`POST /v1/conversations` takes `participants[].user_id`; the app sends the `sup_*` id there (the service accepts any string),
so the conversation is addressed to a user id nobody owns and the supplier cannot answer. Need: a supplier-id -> user-id
resolution (or a `supplier_ref` field on `ConversationCreate`). Until then the chat title in the app falls back to the id.

Also: `POST /v1/shipments/{id}/refresh` right after create returns 429 `refresh_throttled` (60 s); the app shows the server message.
