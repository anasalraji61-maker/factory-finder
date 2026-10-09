"""Built-in gazetteer: countries, regions, provinces and cities (Arabic + English names).

Loaded from ``ff_assistant/data/places_*.json``. ``names`` are matched anywhere in the text;
``strict_names`` are ordinary Arabic words too (كوت = coat, الرياض = gardens, جدة = grandmother)
and are only accepted after a direction marker — the parser enforces that using the
``strict`` flag of a :class:`PlaceHit`.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from functools import cache
from typing import Literal

from ff_assistant.data import load_json, place_files
from ff_assistant.domain.matching import PhraseIndex, PhraseMatch
from ff_assistant.domain.models import Location
from ff_assistant.domain.text import Token, clean_text, fold, tokenize

PlaceType = Literal["city", "country", "region", "province"]
_VALID_TYPES = frozenset({"city", "country", "region", "province"})


@dataclass(frozen=True, slots=True)
class Place:
    id: str
    type: PlaceType
    cc: str | None
    en: str
    ar: str
    capital: str | None = None
    members: tuple[str, ...] = ()

    def name(self, locale: str) -> str:
        return self.ar if locale == "ar" else self.en

    @property
    def countries(self) -> tuple[str, ...]:
        if self.type == "region":
            return self.members
        return (self.cc,) if self.cc else ()


@dataclass(frozen=True, slots=True)
class PlaceHit:
    match: PhraseMatch[Place]
    strict: bool

    @property
    def place(self) -> Place:
        return self.match.value


@dataclass(slots=True)
class Gazetteer:
    places: dict[str, Place]
    _loose: PhraseIndex[Place] = field(default_factory=PhraseIndex)
    _strict: PhraseIndex[Place] = field(default_factory=PhraseIndex)
    _demonyms: PhraseIndex[Place] = field(default_factory=PhraseIndex)
    _countries: dict[str, Place] = field(default_factory=dict)
    _by_city_name: dict[str, Place] = field(default_factory=dict)

    @classmethod
    def from_records(cls, records: Iterable[dict]) -> Gazetteer:
        gaz = cls(places={})
        raw: list[dict] = list(records)
        for rec in raw:
            place = _place_from_record(rec)
            if place.id in gaz.places:
                raise ValueError(f"duplicate place id {place.id}")
            gaz.places[place.id] = place
            if place.type == "country":
                assert place.cc is not None
                gaz._countries[place.cc] = place
        for rec in raw:
            place = gaz.places[rec["id"]]
            if place.capital is not None and place.capital not in gaz.places:
                raise ValueError(f"{place.id}: unknown capital {place.capital}")
            for member in place.members:
                if member not in gaz._countries:
                    raise ValueError(f"{place.id}: unknown member country {member}")
            for name in rec.get("names", []):
                gaz._loose.add(name, place)
            for name in rec.get("strict_names", []):
                gaz._strict.add(name, place)
            for name in rec.get("demonyms", []):
                gaz._demonyms.add(name, place)
            if place.type == "city":
                gaz._by_city_name.setdefault(fold(clean_text(place.en)), place)
        return gaz

    @classmethod
    def default(cls) -> Gazetteer:
        return _default_gazetteer()

    # -- lookups -------------------------------------------------------------------------
    def get(self, place_id: str) -> Place:
        return self.places[place_id]

    def country(self, cc: str) -> Place | None:
        return self._countries.get(cc.upper())

    def country_codes(self) -> frozenset[str]:
        return frozenset(self._countries)

    def resolve(self, place: Place) -> Place:
        """Provinces resolve to their capital city."""
        if place.type == "province" and place.capital:
            return self.places[place.capital]
        return place

    def city_by_name(self, name: str, cc: str | None = None) -> Place | None:
        """Find a city by English or Arabic name (used to validate LLM output)."""
        place = self._by_city_name.get(fold(clean_text(name)))
        if place is None:
            hits = self.find(name)
            place = next((h for h in hits if h.type == "city"), None)
        if place is not None and cc is not None and place.cc != cc.upper():
            return None
        return place

    def city_for_location(self, location: Location) -> Place | None:
        if not location.city:
            return None
        return self.city_by_name(location.city, location.country_code)

    def match_at(
        self,
        tokens: Sequence[Token],
        i: int,
        consumed: Sequence[bool] | None = None,
    ) -> PlaceHit | None:
        loose = self._loose.match_at(tokens, i, consumed)
        strict = self._strict.match_at(tokens, i, consumed)
        if loose is None and strict is None:
            return None
        if strict is None or (loose is not None and loose.length >= strict.length):
            assert loose is not None
            return PlaceHit(loose, strict=False)
        return PlaceHit(strict, strict=True)

    def demonym_at(
        self,
        tokens: Sequence[Token],
        i: int,
        consumed: Sequence[bool] | None = None,
    ) -> PhraseMatch[Place] | None:
        return self._demonyms.match_at(tokens, i, consumed)

    def find(self, text: str) -> list[Place]:
        """All loose (non-strict) place mentions in ``text``, resolved, in order."""
        clean = clean_text(text)
        tokens = tokenize(clean, fold(clean))
        out: list[Place] = []
        i = 0
        while i < len(tokens):
            hit = self.match_at(tokens, i)
            if hit is None or hit.strict:
                i += 1
                continue
            out.append(self.resolve(hit.place))
            i = hit.match.end
        return out

    def to_location(self, place: Place) -> Location | None:
        place = self.resolve(place)
        if place.type == "region" or place.cc is None:
            return None
        if place.type == "city":
            return Location(country_code=place.cc, city=place.en)
        return Location(country_code=place.cc)

    def display_name(self, location: Location, locale: str) -> str:
        """Localized name for a Location (city if known, else country, else raw values)."""
        if location.city:
            city = self.city_for_location(location)
            if city is not None:
                return city.name(locale)
            return location.city
        country = self.country(location.country_code)
        return country.name(locale) if country else location.country_code


def _place_from_record(rec: dict) -> Place:
    place_type = rec.get("type")
    if place_type not in _VALID_TYPES:
        raise ValueError(f"{rec.get('id')}: invalid type {place_type!r}")
    cc = rec.get("cc")
    if place_type != "region" and not cc:
        raise ValueError(f"{rec['id']}: country code required")
    if not rec.get("names") and not rec.get("strict_names"):
        raise ValueError(f"{rec['id']}: at least one name required")
    return Place(
        id=rec["id"],
        type=place_type,
        cc=cc,
        en=rec["en"],
        ar=rec["ar"],
        capital=rec.get("capital"),
        members=tuple(rec.get("members", ())),
    )


@cache
def _default_gazetteer() -> Gazetteer:
    records: list[dict] = []
    for name in place_files():
        records.extend(load_json(name)["places"])
    return Gazetteer.from_records(records)
