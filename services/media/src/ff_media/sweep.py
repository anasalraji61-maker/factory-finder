"""Orphan sweeper CLI: ``python -m ff_media.sweep [--apply]`` (dry run by default; run from cron)."""

from __future__ import annotations

import asyncio
import json
import sys

from ff_media.config import Settings
from ff_media.db import make_engine
from ff_media.service import MediaService
from ff_media.storage import build_storage


async def _run(apply: bool) -> dict[str, int]:
    settings = Settings()
    engine = make_engine(settings.database_url)
    try:
        return await MediaService(engine, settings, build_storage(settings)).sweep_orphans(dry_run=not apply)
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    print(json.dumps(asyncio.run(_run("--apply" in args))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
