#!/usr/bin/env python3
"""Compare each service's FastAPI routes (app.openapi()) with contracts/openapi/<svc>.yaml.

Only method+path sets are compared (no $ref resolution). Exits 1 on any mismatch.

    python scripts/contract_check.py [service ...]
"""
from __future__ import annotations

import importlib
import os
import re
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}
# Gateway-owned routes only; the rest of the gateway surface is a proxy documented in the same file.
IGNORE_PATHS = {"/health"}
# Documented in the contract but invisible to app.openapi() (catch-all proxy, WebSocket).
DOC_ONLY = {"gateway": {("GET", "/v1/{}"), ("GET", "/v1/ws/conversations/{}")}}


def norm(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "{}", path.rstrip("/") or "/")


def ops(paths: dict) -> set[tuple[str, str]]:
    return {(m.upper(), norm(p)) for p, item in paths.items() for m in item if m in METHODS and p not in IGNORE_PATHS}


def main(argv: list[str]) -> int:
    os.chdir(tempfile.mkdtemp())  # services create sqlite files relative to cwd
    names = argv or sorted(p.stem for p in (ROOT / "contracts" / "openapi").glob("*.yaml"))
    bad = 0
    for name in names:
        sys.path.insert(0, str(ROOT / "services" / name / "src"))
        app = importlib.import_module(f"ff_{name}.main").app
        try:
            spec = yaml.safe_load((ROOT / "contracts" / "openapi" / f"{name}.yaml").read_text())
        except yaml.YAMLError as e:
            print(f"DRIFT {name}: contract is not valid YAML: {e}")
            bad += 1
            continue
        code, doc = ops(app.openapi()["paths"]), ops(spec.get("paths", {})) - DOC_ONLY.get(name, set())
        undocumented, unimplemented = sorted(code - doc), sorted(doc - code)
        status = "OK" if not (undocumented or unimplemented) else "DRIFT"
        print(f"{status:5} {name}: {len(code)} routes, {len(doc)} documented")
        for m, p in undocumented:
            print(f"      in code, not in contract:  {m} {p}")
        for m, p in unimplemented:
            print(f"      in contract, not in code:  {m} {p}")
        bad += bool(undocumented or unimplemented)
        sys.path.pop(0)
        for mod in [m for m in sys.modules if m.startswith("ff_")]:
            del sys.modules[mod]
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
