"""Orphan sweeper CLI: ``python -m ff_media.sweep [--apply]`` (dry run by default; run from cron)."""

from __future__ import annotations

import asyncio
import json
import sys

from ff_media.config import Settings
from ff_media.db import make_engine
from ff_media.service import MediaService
from ff_media.storage import build_storage


async def _run(apply: bool) -> dict:
    settings = Settings()
    engine = make_engine(settings.database_url)
    try:
        svc = MediaService(engine, settings, build_storage(settings))
        total: dict = {"scanned": 0, "orphans": 0, "deleted": 0, "rows_missing_blob": 0}
        after = None
        while True:  # each call is time-bounded; resume from its cursor until complete
            res = await svc.sweep_orphans(dry_run=not apply, after=after)
            for k in total:
                total[k] += int(res.get(k, 0))
            if res.get("unsupported"):
                total["unsupported"] = 1
            after = res.get("next_after")
            if res.get("complete", True) or not after:
                return total
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    print(json.dumps(asyncio.run(_run("--apply" in args))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
