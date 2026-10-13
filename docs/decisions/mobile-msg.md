2026-10-13 | messaging/tracking contracts were absent, so live repositories follow ARCHITECTURE §4 with tolerant JSON parsing (list or {items}, nested or flat participant/context) | Contracts may still change; parsing accepts both.
2026-10-13 | Chat uses 4 s HTTP polling, no websocket | No websocket package is allowed in pubspec.
2026-10-13 | Chat state lives in the screen (list + pure helpers in chat_logic.dart) | Optimistic send/merge logic is unit-testable without Riverpod.
2026-10-13 | Mock supplier replies are scheduled 3 s in the future and hidden until the clock passes them | Demonstrates polling without timers.
2026-10-13 | Tracking validators return i18n keys, not text | Keeps validators pure and bilingual.
2026-10-13 | Date helpers duplicated in tracking_widgets.dart | Features must not import each other's internals.
