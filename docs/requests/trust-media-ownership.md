# Request: verifiable uploader -> verification document link (owner: media, consumer: trust, gateway)

Trust only validates the format of `/v1/media/private/<id>.<ext>` references. To prove the submitting supplier uploaded the file, one of:
1. media: internal endpoint `GET /v1/media/internal/files/{id}/owner` (internal token) returning `{"owner_user_id": ...}`, and the gateway (which knows user id and verified supplier id) checks it before forwarding `POST /v1/trust/verification/documents`; or
2. media returns an HMAC-signed `ref` field on private uploads (id + owner), and trust accepts it as an optional additive `file_proofs[]` field.

Also (security-review-2026-10-e item 4): the gateway could forward `X-Account-Age-Days` / `X-Email-Verified` to trust so report eviction/weighting can ignore throwaway accounts. Both are additive; trust continues with its current mitigation meanwhile.
