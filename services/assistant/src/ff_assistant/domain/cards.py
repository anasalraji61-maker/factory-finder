"""Structured 'cards' returned next to ``answer_text`` so the mobile app can render rich widgets later.

Every card is bilingual (``title``/``title_ar``, ``label``/``label_ar``) so the client picks by locale;
values are display strings. Only fields the caller is entitled to see are ever put in a card.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class CardType(StrEnum):
    SHIPMENT_STATUS = "shipment_status"
    DEAL_STATUS = "deal_status"
    LISTING_COMPARISON = "listing_comparison"
    HS_CODE = "hs_code"
    NOTICE = "notice"


class CardRow(BaseModel):
    key: str
    label: str
    label_ar: str
    value: str | None = None  # single-value rows
    value_ar: str | None = None
    values: list[str] | None = None  # comparison rows: one entry per column
    highlight: int | None = None  # comparison rows: index of the better column, when meaningful


class CardColumn(BaseModel):
    id: str
    title: str
    title_ar: str | None = None


class Card(BaseModel):
    type: CardType
    title: str
    title_ar: str
    severity: Literal["info", "ok", "warning", "error"] = "info"
    rows: list[CardRow] = Field(default_factory=list)
    columns: list[CardColumn] | None = None
    refs: dict[str, str] = Field(default_factory=dict)  # ids the app may deep-link (shipment/deal/listing/hs)
    footnote: str | None = None
    footnote_ar: str | None = None


def row(key: str, label: str, label_ar: str, value: str | None, value_ar: str | None = None) -> CardRow:
    return CardRow(key=key, label=label, label_ar=label_ar, value=value, value_ar=value_ar)


def notice(code: str, title: str, title_ar: str, severity: Literal["info", "ok", "warning", "error"] = "info") -> Card:
    return Card(type=CardType.NOTICE, title=title, title_ar=title_ar, severity=severity, refs={"code": code})
