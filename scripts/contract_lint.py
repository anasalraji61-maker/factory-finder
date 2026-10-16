#!/usr/bin/env python3
"""Lint contracts/openapi/*.yaml (read-only; never edits contracts).

Checks: operation-id (present + unique), summary, responses (>=1 2xx and >=1 4xx
that references the shared Error schema), ref (every $ref resolves), money-float
(float `number` for money-like names), enum (non-empty), example (delegates to
scripts/contract_examples.py).

    python scripts/contract_lint.py            # exit 1 on any finding
    python scripts/contract_lint.py --json     # machine readable
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
OPENAPI = ROOT / "contracts" / "openapi"
METHODS = {"get", "put", "post", "delete", "patch", "options", "head"}
MONEY = re.compile(r"(amount|price|cost|total|fee|commission)", re.I)
ERROR_REFS = ("#/components/responses/Error", "common.schema.json#/$defs/Error",
              "#/components/schemas/Error")
_json_cache: dict[Path, object] = {}

# Liveness/readiness probes: no client-error path exists, so no 4xx is required.
PROBE_PATHS = {"/health", "/ready"}
# WebSocket upgrade: success is 101 Switching Protocols, not 2xx.
NO_2XX_OK = {("gateway.yaml", "GET", "/v1/ws/conversations/{conversation_id}")}
# Accepted deviations (float `number` for money-like names). Changing the type
# would break existing clients; see docs/fixes/contract-lint.md.
MONEY_FLOAT_ALLOW = {
    ("freight.yaml", "/components/schemas/Comparison/properties/items/items/properties/price_delta"),
    ("sourcing.yaml", "/paths//v1/search/get/parameters/5"),  # min_price
    ("sourcing.yaml", "/paths//v1/search/get/parameters/6"),  # max_price
}


def resolve_ref(ref: str, doc: dict, base: Path):
    """Return (found, target)."""
    file_part, _, frag = ref.partition("#")
    if file_part:
        p = (base.parent / file_part).resolve()
        if not p.exists():
            return False, None
        if p not in _json_cache:
            text = p.read_text()
            _json_cache[p] = yaml.safe_load(text)
        node = _json_cache[p]
    else:
        node = doc
    for part in [x for x in frag.split("/") if x]:
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        else:
            return False, None
    return True, node


def mentions_error(node, seen=0) -> bool:
    s = json.dumps(node, default=str)
    return any(r in s for r in ERROR_REFS)


def walk(node, path=""):
    yield path, node
    if isinstance(node, dict):
        for k, v in node.items():
            yield from walk(v, f"{path}/{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from walk(v, f"{path}/{i}")


def lint_file(f: Path, out: list):
    doc = yaml.safe_load(f.read_text())
    name = f.name

    def add(cat, where, msg):
        if cat == "money-float" and (name, where.split(":")[0]) in MONEY_FLOAT_ALLOW:
            return
        out.append({"category": cat, "file": name, "where": where, "message": msg})

    ids = Counter()
    for p, ops in (doc.get("paths") or {}).items():
        for m, op in ops.items():
            if m not in METHODS or not isinstance(op, dict):
                continue
            where = f"{m.upper()} {p}"
            oid = op.get("operationId")
            if not oid:
                add("operation-id", where, "missing operationId")
            else:
                ids[oid] += 1
            if not op.get("summary"):
                add("summary", where, "missing summary")
            resp = op.get("responses") or {}
            codes = [str(c) for c in resp]
            if not any(c.startswith("2") for c in codes) and (name, m.upper(), p) not in NO_2XX_OK:
                add("responses", where, "no 2xx response")
            fours = [c for c in codes if c.startswith("4")]
            if p in PROBE_PATHS:
                pass
            elif not fours:
                add("responses", where, "no 4xx response")
            elif not any(mentions_error(resp[c]) or mentions_error(resp.get(int(c), "")) for c in fours):
                add("responses", where, "4xx responses do not reference the shared Error schema")
    for oid, n in ids.items():
        if n > 1:
            add("operation-id", oid, f"operationId duplicated {n}x")

    for p, node in walk(doc):
        if not isinstance(node, dict):
            continue
        if "$ref" in node and isinstance(node["$ref"], str):
            ok, _ = resolve_ref(node["$ref"], doc, f)
            if not ok:
                add("ref", p, f"unresolved $ref {node['$ref']}")
        if "enum" in node and (not isinstance(node["enum"], list) or not node["enum"]):
            add("enum", p, "empty enum")
        props = node.get("properties")
        if isinstance(props, dict):
            for k, v in props.items():
                if "ratio" in str(k).lower() or "/weights" in p:
                    continue  # dimensionless ratios / scoring weights, not money
                if (MONEY.search(str(k)) and isinstance(v, dict) and v.get("type") == "number"
                        and "string" not in str(v.get("type"))):
                    add("money-float", f"{p}/properties/{k}",
                        f"money-like field '{k}' is float `number` (use decimal string or integer minor units)")
        if (p.rsplit("/", 2)[-2:-1] == ["parameters"] or "in" in node) and "schema" in node \
                and MONEY.search(str(node.get("name", ""))) and isinstance(node["schema"], dict) \
                and node["schema"].get("type") == "number":
            add("money-float", p, f"money-like parameter '{node['name']}' is float `number`")


def main() -> int:
    findings: list = []
    for f in sorted(OPENAPI.glob("*.yaml")):
        lint_file(f, findings)
    ex = subprocess.run([sys.executable, str(ROOT / "scripts" / "contract_examples.py")],
                        capture_output=True, text=True, cwd=ROOT)
    if ex.returncode != 0:
        for line in (ex.stdout + ex.stderr).splitlines():
            if line.strip() and "checked" not in line:
                findings.append({"category": "example", "file": "-", "where": "-", "message": line.strip()})
    counts = Counter(x["category"] for x in findings)
    if "--json" in sys.argv:
        print(json.dumps({"counts": counts, "findings": findings}, indent=1))
    else:
        for x in findings:
            print(f"[{x['category']}] {x['file']} {x['where']}: {x['message']}")
        print(f"\ncontract-lint: {len(findings)} finding(s) {dict(counts)}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
