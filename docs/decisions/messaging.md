2026-10-13 | Unread count derived as last_seq - last_read_seq (sender's pointer advances on send) | no per-recipient counters
2026-10-13 | Conversation POST returns 201 new / 200 existing; message POST 201 new / 200 idempotent replay | clear idempotency signal
2026-10-13 | Abuse words flag by default (configurable mask/reject) | spec: basic safety, avoid false-positive blocking
2026-10-13 | WS authenticates with X-User-Id header or ?user_id= (only without internal token); close codes 4401/4403/4429 | dev convenience, safe behind gateway
