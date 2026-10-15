"""Bundled dataset loading and startup validation."""

import json
import re
from functools import lru_cache
from importlib import resources

from .models import City, Country, Hub


class DatasetError(ValueError):
    pass


def _load(name: str) -> list[dict] | dict:
    return json.loads(resources.files("ff_geo.data").joinpath(f"{name}.json").read_text("utf-8"))


class Dataset:
    def __init__(
        self,
        countries: list[Country],
        cities: list[City],
        hubs: list[Hub],
        aliases: dict[str, list[str]] | None = None,
    ):
        self.countries = countries
        self.aliases = aliases or {}
        self.cities = cities
        self.hubs = hubs
        self.country_by_code = {c.iso2: c for c in countries}
        self.validate()

    def validate(self) -> None:
        codes = [c.iso2 for c in self.countries]
        if len(set(codes)) != len(codes):
            raise DatasetError("duplicate country codes")
        for kind, items in (("city", self.cities), ("hub", self.hubs)):
            ids = [i.id for i in items]
            if len(set(ids)) != len(ids):
                dup = sorted({i for i in ids if ids.count(i) > 1})
                raise DatasetError(f"duplicate {kind} ids: {dup}")
            for i in items:
                if i.country_code not in self.country_by_code:
                    raise DatasetError(f"{kind} {i.id}: unknown country {i.country_code}")
                if not i.name_ar.strip() or not i.name_en.strip():
                    raise DatasetError(f"{kind} {i.id}: missing name")
        city_ids = {c.id for c in self.cities}
        for cid, names in self.aliases.items():
            if cid not in city_ids:
                raise DatasetError(f"aliases: unknown city {cid}")
            if not names or any(not isinstance(n, str) or not n.strip() for n in names):
                raise DatasetError(f"aliases: bad entry for {cid}")
        for h in self.hubs:
            if h.type == "sea" and not (h.unlocode and re.fullmatch(r"[A-Z]{5}", h.unlocode)):
                raise DatasetError(f"sea hub {h.id}: bad UN/LOCODE")
            if h.type == "air" and not (h.iata and re.fullmatch(r"[A-Z]{3}", h.iata)):
                raise DatasetError(f"air hub {h.id}: bad IATA")
            if not h.serves_countries:
                raise DatasetError(f"hub {h.id}: serves_countries empty")


@lru_cache(maxsize=1)
def get_dataset() -> Dataset:
    return Dataset(
        [Country(**c) for c in _load("countries")],
        [City(**c) for c in _load("cities")],
        [Hub(**h) for h in _load("hubs")],
        _load("aliases"),
    )
