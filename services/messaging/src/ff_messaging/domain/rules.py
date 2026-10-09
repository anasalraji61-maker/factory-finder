"""Pure business rules: participant resolution, previews, typing throttle, dedupe keys."""

import time
from collections.abc import Callable, Sequence

from ff_messaging.domain.errors import InvalidInputError
from ff_messaging.domain.models import ContextType, ConversationContext, ParticipantSpec, Role


def resolve_participants(
    *,
    caller: str | None,
    requested: Sequence[ParticipantSpec],
    my_role: Role | None,
    context: ConversationContext | None,
    platform_user_ids: frozenset[str],
    support_user_id: str | None,
    max_participants: int,
) -> tuple[ParticipantSpec, ...]:
    """Final, ordered participant list for a new conversation.

    * the caller (when given) is always a participant and comes first; their role is taken from
      ``requested`` if listed there, else ``my_role``, else ``platform``/``buyer``;
    * ``support`` conversations automatically include the support account;
    * only configured platform accounts may hold the ``platform`` role, and they always do
      (prevents users from impersonating platform staff);
    * at least two distinct participants, at most ``max_participants``.
    """
    roles: dict[str, Role] = {}
    for spec in requested:
        if spec.user_id in roles:
            raise InvalidInputError(
                "A participant is listed more than once",
                code="duplicate_participant",
                details={"user_id": spec.user_id},
            )
        roles[spec.user_id] = spec.role

    ordered: list[ParticipantSpec] = []
    if caller is not None:
        if caller in roles:
            role = roles.pop(caller)
            if my_role is not None and my_role is not role:
                raise InvalidInputError(
                    "my_role conflicts with the caller's role in participants",
                    code="conflicting_role",
                )
        else:
            role = my_role or (Role.PLATFORM if caller in platform_user_ids else Role.BUYER)
        ordered.append(ParticipantSpec(caller, role))
    ordered.extend(ParticipantSpec(user_id, role) for user_id, role in roles.items())

    if (
        context is not None
        and context.type is ContextType.SUPPORT
        and support_user_id
        and not any(p.user_id in platform_user_ids for p in ordered)
    ):
        ordered.append(ParticipantSpec(support_user_id, Role.PLATFORM))

    resolved: list[ParticipantSpec] = []
    for spec in ordered:
        is_platform_account = spec.user_id in platform_user_ids
        if spec.role is Role.PLATFORM and not is_platform_account:
            raise InvalidInputError(
                "Only platform accounts can take the platform role",
                code="invalid_role",
                details={"user_id": spec.user_id},
            )
        resolved.append(
            ParticipantSpec(spec.user_id, Role.PLATFORM) if is_platform_account else spec
        )

    if len(resolved) < 2:
        raise InvalidInputError(
            "A conversation needs at least two distinct participants",
            code="not_enough_participants",
        )
    if len(resolved) > max_participants:
        raise InvalidInputError(
            "Too many participants",
            code="too_many_participants",
            details={"max_participants": max_participants},
        )
    return tuple(resolved)


def make_preview(text: str | None, limit: int) -> str | None:
    """Single-line preview of a message for conversation lists."""
    if not text:
        return None
    single_line = " ".join(text.split())
    if len(single_line) <= limit:
        return single_line
    return single_line[: limit - 1].rstrip() + "…"


def user_message_dedupe_key(sender_id: str, client_message_id: str) -> str:
    # "/" never appears in user ids or client ids, so user and system keys cannot collide.
    return f"u:{sender_id}/{client_message_id}"


def system_message_dedupe_key(client_message_id: str) -> str:
    return f"s:/{client_message_id}"


class TypingThrottle:
    """Limits typing broadcasts per (conversation, user) key.

    ``is_typing=True`` is broadcast at most once per ``interval_seconds``; ``is_typing=False`` is
    broadcast only when a start was broadcast before (no noise from idle clients).
    """

    def __init__(
        self,
        *,
        interval_seconds: float,
        clock: Callable[[], float] = time.monotonic,
        max_keys: int = 100_000,
    ) -> None:
        self.interval = interval_seconds
        self._clock = clock
        self._max_keys = max_keys
        self._last: dict[str, float] = {}

    def should_broadcast(self, key: str, is_typing: bool) -> bool:
        if not is_typing:
            return self._last.pop(key, None) is not None
        now = self._clock()
        last = self._last.get(key)
        if last is not None and now - last < self.interval:
            return False
        if last is None and len(self._last) >= self._max_keys:
            self._prune(now)
        self._last[key] = now
        return True

    def forget(self, key: str) -> None:
        """Drop state for ``key`` (e.g. the user just sent a message, so typing has ended)."""
        self._last.pop(key, None)

    def _prune(self, now: float) -> None:
        horizon = max(self.interval, 60.0)
        for key in [k for k, at in self._last.items() if now - at >= horizon]:
            del self._last[key]
