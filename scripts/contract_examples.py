#!/usr/bin/env python3
"""Validate every `example` / `examples` in contracts/openapi/*.yaml against the schema it documents.

Offline and deterministic (no services are started). Examples are found anywhere in a spec:
  * schema-level  `example: {...}` / `examples: [...]`  -> validated against that schema node
  * media-type / parameter `example` / `examples: {name: {value: ...}}` -> validated against its `schema`
`$ref` is resolved across `#/components/...` and `../schemas/common.schema.json` (JSON Schema 2020-12).

    python scripts/contract_examples.py        # exit 1 on any invalid example
    python scripts/contract_examples.py -v     # also list every validated example

Requires: pyyaml, jsonschema, referencing.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

ROOT = Path(__file__).resolve().parent.parent
OPENAPI = ROOT / "contracts" / "openapi"
COMMON_ID = "https://factory-finder.dev/schemas/common.schema.json"
VERBOSE = "-v" in sys.argv


def _retrieve(uri: str) -> Resource:
    if uri == COMMON_ID:
        uri = (ROOT / "contracts" / "schemas" / "common.schema.json").as_uri()
    path = Path(uri.removeprefix("file://"))
    data = json.loads(path.read_text()) if path.suffix == ".json" else yaml.safe_load(path.read_text())
    return Resource.from_contents(data, default_specification=DRAFT202012)


REGISTRY: Registry = Registry(retrieve=_retrieve)  # type: ignore[call-arg]


def _ptr(parts: list[str]) -> str:
    return "#/" + "/".join(p.replace("~", "~0").replace("/", "~1") for p in parts)


def find_examples(node, path: list[str] | None = None, parent_key: str = ""):
    """Yield (pointer_parts_of_schema, example_value, label) for every example in the document."""
    path = path or []
    if isinstance(node, list):
        for i, v in enumerate(node):
            yield from find_examples(v, [*path, str(i)], parent_key)
        return
    if not isinstance(node, dict):
        return
    in_props = parent_key in ("properties", "patternProperties", "paths", "components", "schemas", "responses",
                              "parameters", "content", "headers", "examples")
    carries_schema = "schema" in node and isinstance(node["schema"], dict)
    if not in_props or carries_schema:
        if "example" in node and (carries_schema or "type" in node or "$ref" in node or "allOf" in node or "oneOf" in node):
            yield [*path, "schema"] if carries_schema else path, node["example"], "example"
        ex = node.get("examples")
        if isinstance(ex, dict) and carries_schema:
            for name, v in ex.items():
                if isinstance(v, dict) and "value" in v:
                    yield [*path, "schema"], v["value"], f"examples.{name}"
        elif isinstance(ex, list):
            for i, v in enumerate(ex):
                yield path, v, f"examples[{i}]"
    for k, v in node.items():
        if k in ("example", "examples") and not (isinstance(v, dict) and parent_key == "properties"):
            continue
        yield from find_examples(v, [*path, k], k)


def check_file(spec_path: Path) -> tuple[int, list[str]]:
    spec = yaml.safe_load(spec_path.read_text())
    base = spec_path.as_uri()
    n, errors = 0, []
    for parts, value, label in find_examples(spec):
        n += 1
        where = f"{spec_path.name}{_ptr(parts)} [{label}]"
        try:
            v = Draft202012Validator({"$ref": base + _ptr(parts)}, registry=REGISTRY)
            errs = sorted(v.iter_errors(value), key=lambda e: list(e.absolute_path))
        except Exception as exc:  # unresolvable ref etc.
            errors.append(f"{where}: cannot validate ({type(exc).__name__}: {exc})")
            continue
        for e in errs[:5]:
            loc = "/".join(str(p) for p in e.absolute_path) or "<root>"
            errors.append(f"{where}: at {loc}: {e.message[:200]}")
        if VERBOSE and not errs:
            print(f"ok  {where}")
    return n, errors


def main() -> int:
    total, errors = 0, []
    for p in sorted(OPENAPI.glob("*.yaml")):
        n, errs = check_file(p)
        total += n
        errors += errs
    for e in errors:
        print("FAIL", e)
    print(f"contract examples: {total} checked, {len(errors)} problem(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
