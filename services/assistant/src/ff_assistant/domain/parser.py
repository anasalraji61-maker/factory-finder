"""Deterministic rule-based parser: Arabic (incl. Iraqi dialect) / English text -> ParsedQuery."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from ff_assistant import guard
from ff_assistant.domain import lexicon as lx
from ff_assistant.domain.gazetteer import Gazetteer
from ff_assistant.domain.matching import canon, in_set
from ff_assistant.domain.models import Condition, Incoterm, ListingKind, Location
from ff_assistant.domain.query import Budget, Intent, ParsedQuery
from ff_assistant.domain.text import (
    Token,
    clean_text,
    detect_language,
    fold,
    is_arabic,
    mask_spans,
    tokenize,
)

_THOUSANDS = re.compile(r"^\d{1,3}(,\d{3})+(\.\d+)?$")


def _num(text: str) -> Decimal | None:
    text = text.replace(",", "") if _THOUSANDS.match(text) else text.replace(",", ".")
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _is(tok: Token | None, words: frozenset[str]) -> bool:
    return tok is not None and tok.is_word and in_set(tok.norm, words, clitics=False)


def _has(tokens: list[Token], words: frozenset[str]) -> bool:
    return any(t.is_word and in_set(t.norm, words, clitics=True) for t in tokens)


def _currency(tok: Token | None) -> str | None:
    if tok is None or tok.kind == "num":
        return None
    return lx.CURRENCIES.get(canon(tok.norm)) or lx.CURRENCIES.get(tok.norm)


def parse(text: str, gaz: Gazetteer | None = None, default_destination: Location | None = None) -> ParsedQuery:
    gaz = gaz or Gazetteer.default()
    if guard.is_injection(text):  # instructions aimed at the assistant are never parsed into tool calls
        return ParsedQuery(intent=Intent.HELP, language=detect_language(clean_text(text)), confidence=1.0)
    clean = clean_text(text)
    special = lx.special_request(clean)
    if special == "message":  # private messages are app actions, never parsed into tool calls
        return ParsedQuery(intent=Intent.HELP, language=detect_language(clean), confidence=1.0)
    rfq = special == "rfq"  # RFQ: parsed into a DRAFT only (the assistant never posts anything)

    # 1. references (masked afterwards so they never leak into keywords)
    spans: list[tuple[int, int]] = []
    reference = reference_type = supplier_id = None
    for rtype, rx in lx.REF_RES.items():
        m = rx.search(clean)
        if m:
            reference_type, spans = rtype, [*spans, m.span()]
            raw = m.group().strip()
            reference = re.sub(r"(?i)imo\s?[:#]?\s?", "", raw).replace(" ", "").upper()
            if rtype == "vessel_imo":
                reference = "IMO" + reference.lstrip("IMO")
            break
    sm = lx.SUPPLIER_RE.search(clean)
    if sm:
        supplier_id = sm.group().lower()
        spans.append(sm.span())
    listing_ids: list[str] = []
    for lm in lx.LISTING_RE.finditer(clean):
        if lm.group().lower() not in listing_ids:
            listing_ids.append(lm.group().lower())
        spans.append(lm.span())
    incoterm = None
    im = lx.INCOTERM_RE.search(clean)
    if im:
        incoterm = Incoterm.FOB if im.group(2) else Incoterm(im.group(1).upper())
        spans.append(im.span())
    dm = lx.DEAL_RE.search(clean)
    deal_id = dm.group().lower() if dm else None
    if dm:
        spans.append(dm.span())
    hs_phrase = lx.HS_RE.search(clean) is not None
    hs_code = None
    if hs_phrase and reference is None:
        hm = lx.HS_CODE_RE.search(clean)
        if hm:
            hs_code = re.sub(r"\D", "", hm.group())
            spans.append(hm.span())
    masked = mask_spans(clean, spans)
    language = detect_language(masked) if masked.strip() else detect_language(clean)  # ids/refs are not language evidence
    tokens = tokenize(masked, fold(masked))
    used = [False] * len(tokens)

    def eat(*idx: int) -> None:
        for i in idx:
            if 0 <= i < len(tokens):
                used[i] = True

    # 2. condition
    condition = None
    for i, t in enumerate(tokens):
        if not t.is_word:
            continue
        for words, cond in ((lx.USED_WORDS, Condition.USED), (lx.REFURB_WORDS, Condition.REFURBISHED), (lx.NEW_WORDS, Condition.NEW)):
            if _is(t, words):
                condition = condition or cond
                eat(i)

    # 3. places
    origin = destination = None
    origin_region = None

    def prev_role(i: int) -> str:
        for back in (1, 2):
            p = tokens[i - back] if i - back >= 0 else None
            if p is None or not p.is_word:
                continue
            if _is(p, lx.TO_MARKERS):
                return "to"
            if _is(p, lx.FROM_MARKERS):
                return "from"
            if _is(p, lx.IN_MARKERS):
                return "in"
        return ""

    i = 0
    while i < len(tokens):
        hit = gaz.match_at(tokens, i, used)
        if hit is None:
            i += 1
            continue
        role = hit.match.role if hit.match.role in ("to", "in") else ""
        marker = role or prev_role(i)
        if hit.strict and not marker:
            i += 1
            continue
        place = gaz.resolve(hit.place)
        loc = gaz.to_location(place)
        if loc is None:
            if place.type == "region" and origin_region is None and marker != "to":
                origin_region = place.en
        else:
            iraqi = loc.country_code == "IQ"
            as_dest = marker == "to" or (marker in ("in", "") and iraqi)
            if marker == "from":
                as_dest = False
            if as_dest and destination is None:
                destination = loc
            elif not as_dest and origin is None or not as_dest and origin is not None and origin.city is None and loc.city and loc.country_code == origin.country_code:
                origin = loc
        eat(*range(hit.match.start, hit.match.end))
        if hit.match.start > 0 and not hit.match.role:
            for back in (1, 2):
                j = hit.match.start - back
                if j >= 0 and _is(tokens[j], lx.TO_MARKERS | lx.FROM_MARKERS | lx.IN_MARKERS):
                    eat(j)
        i = hit.match.end
    if origin is None and origin_region is None:
        for i in range(len(tokens)):
            m = gaz.demonym_at(tokens, i, used)
            if m is not None and m.value.cc and m.value.type == "country":
                origin = Location(country_code=m.value.cc)
                eat(*range(m.start, m.end))
                break
    if destination is None:
        destination = default_destination

    # 4. budget
    budget = None
    for i, t in enumerate(tokens):
        if not t.is_num or used[i]:
            continue
        amount = _num(t.norm)
        if amount is None:
            continue
        after = _currency(tokens[i + 1]) if i + 1 < len(tokens) else None
        before = _currency(tokens[i - 1]) if i > 0 else None
        nxt = tokens[i + 1] if i + 1 < len(tokens) else None
        if not (after or before) and nxt is not None and nxt.is_word and (lx.UNITS.get(canon(nxt.norm)) or lx.UNITS.get(nxt.norm)):
            continue  # "سعر ٢٠٠٠ كيلو": a quantity, not a budget
        cue = False
        bound = "max"
        j = i - 1 - (1 if before else 0)
        for k in range(j, max(j - 3, -1), -1):
            w = tokens[k]
            if not w.is_word:
                continue
            if _is(w, lx.MAX_WORDS):
                eat(k)
                cue = True
            elif _is(w, lx.MIN_WORDS):
                bound, cue = "min", True
                eat(k)
            elif _is(w, lx.BUDGET_CUES):
                cue = True
                eat(k)
        currency = after or before
        if currency or cue:
            budget = Budget(amount=amount, currency=currency or "USD", bound=bound)
            eat(i)
            if after:
                eat(i + 1)
            if before:
                eat(i - 1)
            break

    # 5. quantity / unit
    quantity = unit = None
    for i, t in enumerate(tokens):
        if not t.is_num or used[i]:
            continue
        amount = _num(t.norm)
        if amount is None or amount <= 0:
            continue
        nxt = tokens[i + 1] if i + 1 < len(tokens) else None
        u = None
        if nxt is not None and nxt.is_word and not used[i + 1]:
            u = lx.UNITS.get(canon(nxt.norm)) or lx.UNITS.get(nxt.norm)
        if u is not None:
            quantity, unit = amount, u[0]
            eat(i, i + 1)
            break
        if nxt is not None and nxt.is_word and not used[i + 1]:
            quantity, unit = amount, "piece"
            eat(i)
            break

    # 6. product keywords / kind
    kind = None
    category = None
    keywords: list[str] = []
    for m in lx.KIND_PHRASES.find_all(tokens, used):
        kind = ListingKind(m.value)
        if kind is ListingKind.PRODUCTION_LINE:
            continue  # keep tokens: the glossary may know the specific line
    for m in lx.glossary_index().find_all(tokens, used):
        entry = m.value
        first = tokens[m.start]
        term = entry["en"]
        if not is_arabic(first.norm) and not entry.get("ml") and m.end - m.start >= len(term.split()):
            term = " ".join(t.surface for t in tokens[m.start : m.end])
        if term not in keywords:
            keywords.append(term)
        category = category or entry.get("category")
        if entry.get("kind") and kind is None:
            kind = ListingKind(entry["kind"])
        if entry.get("kind") == "production_line":
            kind = ListingKind.PRODUCTION_LINE
        eat(*range(m.start, m.end))
    for m in lx.KIND_PHRASES.find_all(tokens):
        if kind is None:
            kind = ListingKind(m.value)

    product_found = bool(keywords) or kind is not None
    # 7. intent
    if rfq:
        intent = Intent.CREATE_RFQ_DRAFT
    elif len(listing_ids) >= 2 or (listing_ids and lx.COMPARE_RE.search(clean)):
        intent = Intent.COMPARE
    elif deal_id or (lx.DEAL_PHRASE_RE.search(clean) and not keywords):
        intent = Intent.DEAL_STATUS
    elif hs_phrase and not reference and not supplier_id:
        intent = Intent.HS_LOOKUP
    elif reference and _has(tokens, lx.STATUS_WORDS):
        intent = Intent.SHIPMENT_STATUS
    elif reference or (_has(tokens, lx.TRACK_WORDS) and not supplier_id and not keywords):
        intent = Intent.TRACK
    elif supplier_id or _has(tokens, lx.TRUST_WORDS):
        intent = Intent.TRUST
    elif (_has(tokens, lx.SHIP_WORDS) or lx.DOOR_RE.search(clean) or incoterm) and _has(tokens, lx.COST_WORDS):
        intent = Intent.QUOTE
    elif (not product_found and (lx.OFFTOPIC_RE.search(clean) or lx.COMPLIANCE_RE.search(clean))) or (
        not keywords and (_has(tokens, lx.HELP_WORDS) or len(tokens) <= 2)
    ):
        intent = Intent.HELP
    else:
        intent = Intent.SEARCH

    if intent in (Intent.SEARCH, Intent.QUOTE, Intent.CREATE_RFQ_DRAFT) and not keywords:
        leftover = [
            t
            for t in tokens
            if t.is_word
            and not used[t.index]
            and not in_set(t.norm, lx.STOPWORDS | lx.SHIP_WORDS | lx.COST_WORDS | (lx.RFQ_NOISE if rfq else frozenset()), clitics=True)
        ]
        keywords = [t.surface for t in leftover][:6]

    if intent is Intent.SEARCH and not keywords and kind is None:
        intent = Intent.HELP  # nothing to search for: ask, do not guess

    hs_query = None
    if intent is Intent.HS_LOOKUP and not hs_code:
        hs_query = " ".join(
            t.surface for t in tokens
            if t.is_word and not used[t.index] and not in_set(t.norm, lx.STOPWORDS | lx.HS_NOISE, clitics=True)
            and not lx.HS_RE.fullmatch(t.surface)
        )[:100] or (" ".join(keywords) or None)

    conf = 0.3
    conf += 0.3 if keywords else 0
    conf += 0.15 if destination else 0
    conf += 0.1 if origin or origin_region else 0
    conf += 0.5 if (reference or supplier_id or deal_id or listing_ids or hs_code) else 0
    if intent is Intent.HELP or intent is Intent.CREATE_RFQ_DRAFT:
        conf = 0.8
    return ParsedQuery(
        intent=intent,
        language=language,
        kind=kind,
        condition=condition,
        keywords=keywords,
        query=" ".join(keywords),
        category=category,
        quantity=quantity,
        unit=unit,
        budget=budget,
        origin=origin,
        origin_region=origin_region,
        destination=destination,
        supplier_id=supplier_id,
        reference=reference,
        reference_type=reference_type,
        deal_id=deal_id,
        listing_ids=listing_ids,
        hs_code=hs_code,
        hs_query=hs_query,
        incoterm=incoterm,
        confidence=min(conf, 1.0),
    )
