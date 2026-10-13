2026-10-13 | ChatSocket interface + LiveChatSocket (injected ChatChannel connector) + MockChatSocket; dart:io only in chat_channel_io.dart, web gets a stub via conditional import | Keeps web/test builds compiling and reconnect logic unit-testable.
2026-10-13 | WS only pushes message.created; REST send stays the source of truth, polling kept as fallback | Dedupe by id (appendIncoming / confirmSent).
2026-10-13 | 4401 -> one refreshSession() then reconnect; 4403/4404 fatal; other closes backoff 1,2,4,8,16,30s | Matches gateway README close codes.
2026-10-13 | Added public ApiClient.refreshSession() wrapping the private single-flight refresh | Only way to reuse token refresh without duplicating it.
