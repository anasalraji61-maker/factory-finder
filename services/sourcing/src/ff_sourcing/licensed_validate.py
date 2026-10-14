"""Mapping validator CLI (no network).

    python -m ff_sourcing.licensed_validate mapping.json [more.json ...] [--sample response.json] [--allow-example]

Checks the schema, placeholders, env-var names, secrets-in-file heuristics and prints warnings. With
--sample (a recorded JSON response) it also runs the mapping and reports how many items normalize
and why the rest were dropped. Exit code 0 = all valid, 1 = invalid, 2 = usage.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .adapters.licensed_rest import LicensedRestAdapter, load_mapping, warnings_for


def validate_file(path: str, sample: str | None = None, allow_example: bool = False) -> tuple[bool, list[str]]:
    lines: list[str] = []
    try:
        spec = load_mapping(path)
    except ValueError as exc:
        return False, [f"INVALID {path}: {exc}"]
    if spec.example and not allow_example:
        lines.append("NOTE example=true (fictional provider): fine to validate, refused at runtime")
    lines.append(f"OK {path}: id={spec.id} auth={spec.auth.style} key_env={spec.auth.key_env or '-'}")
    lines += [f"WARN {w}" for w in warnings_for(spec) if not (spec.example and "example=true" in w)]
    if sample:
        try:
            payload = json.loads(Path(sample).read_text("utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return False, [*lines, f"INVALID sample {sample}: {exc}"]
        adapter = LicensedRestAdapter(spec, env={})
        raw = adapter.extract_items(payload)
        ok = 0
        for r in raw:
            try:
                ok += adapter.normalize_item(r) is not None
            except Exception as exc:
                lines.append(f"WARN item error: {type(exc).__name__}")
        lines.append(f"SAMPLE {ok}/{len(raw)} items normalized")
        if raw and ok == 0:
            return False, [*lines, "INVALID mapping produced no listings from the sample"]
    return True, lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="licensed_validate", description=__doc__.split("\n")[0])
    ap.add_argument("files", nargs="+")
    ap.add_argument("--sample", help="recorded JSON response to dry-run the mapping against")
    ap.add_argument("--allow-example", action="store_true")
    a = ap.parse_args(argv)
    good = True
    for f in a.files:
        ok, lines = validate_file(f, a.sample, a.allow_example)
        good &= ok
        print("\n".join(lines))
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
