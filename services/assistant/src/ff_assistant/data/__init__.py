"""Bundled static data (gazetteer, lexicons). Read once and cached."""

from __future__ import annotations

import json
from functools import cache
from importlib import resources
from typing import Any


@cache
def load_json(name: str) -> Any:
    """Load a bundled JSON file from this package (cached, read-only use)."""
    text = resources.files(__package__).joinpath(name).read_text(encoding="utf-8")
    return json.loads(text)


def place_files() -> list[str]:
    return sorted(
        entry.name
        for entry in resources.files(__package__).iterdir()
        if entry.name.startswith("places_") and entry.name.endswith(".json")
    )
