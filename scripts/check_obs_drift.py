#!/usr/bin/env python3
"""Fail if any services/*/src/ff_*/obs.py differs from the others after normalising the package name."""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    files = sorted((ROOT / "services").glob("*/src/ff_*/obs.py"))
    if len(files) < 2:
        print("obs-check: expected several obs.py files, found", len(files))
        return 1
    texts = {f: re.sub(r"ff_[a-z]+", "ff_PKG", f.read_text(encoding="utf-8")) for f in files}
    ref_file = next((f for f in files if "/gateway/" in str(f)), files[0])
    bad = [f for f, t in texts.items() if t != texts[ref_file]]
    for f in bad:
        print(f"DRIFT: {f.relative_to(ROOT)} differs from {ref_file.relative_to(ROOT)}")
    if bad:
        return 1
    print(f"obs-check: {len(files)} obs.py files identical")
    return 0


if __name__ == "__main__":
    sys.exit(main())
