"""Security review 2026-10-j: block-list growth is bounded; re-blocking stays idempotent."""

import pytest

from ff_messaging.config import Settings
from ff_messaging.domain.errors import LimitReachedError
from ff_messaging.main import build_service
from ff_messaging.persistence.database import Database
from ff_messaging.realtime.hub import ConversationHub


@pytest.fixture
async def svc(tmp_path):
    s = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path}/m.db", max_blocks_per_user=3)
    db = Database(s.database_url)
    await db.create_all()
    yield build_service(s, db, ConversationHub())
    await db.dispose()


async def test_block_list_is_capped(svc):
    for i in range(3):
        await svc.block_user("buyer1", f"troll{i}")
    with pytest.raises(LimitReachedError) as e:
        await svc.block_user("buyer1", "troll3")
    assert e.value.code == "block_limit_reached"
    await svc.block_user("buyer1", "troll1")  # already blocked: idempotent, not counted again
    await svc.unblock_user("buyer1", "troll0")
    await svc.block_user("buyer1", "troll3")  # room again
    assert len(await svc.list_blocks("buyer1")) == 3
    await svc.block_user("other", "troll0")  # the cap is per blocker
