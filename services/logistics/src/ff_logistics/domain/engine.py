"""Landed-cost engine. All internal money is USD Decimal; converted once to the display currency."""
import math
import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from ..adapters.fx import FxService, utcnow_iso
from ..clients.geo import GeoClient, Hub, Point
from ..errors import ApiError
from ..schemas import ALL_MODES, LandedCostRequest, MoneyIn
from . import cargo
from .duties import duty_rule, load_json
from .incoterms import BUYER_STAGES, CUSTOMS_ADDS
from .money import D, money, quantize
from .warnings import cargo_warnings, sanctions_warning, value_warnings

ASSUMPTION_TABLE = "Rates, duties and fees come from an approximate table, verify with a customs broker."
SPREAD = {"origin_inland": "0.20", "origin_handling": "0.15", "main_leg": "0.15", "insurance": "0.10",
          "destination_handling": "0.20", "duties": "0.25", "taxes": "0.25", "clearance": "0.25",
          "destination_inland": "0.20", "goods": "0"}
INS_RATE = {"sea": "0.003", "air": "0.002", "road": "0.0035", "rail": "0.003"}
W_COST, W_TIME = Decimal("0.6"), Decimal("0.4")  # recommendation weights


def family(mode: str) -> str:
    return "sea" if mode.startswith("sea") else mode


@dataclass
class Line:
    stage: str
    description: str
    usd: Decimal
    source: str
    estimate: bool = True


@dataclass
class Alt:
    hub: Hub
    via: Hub | None = None
    border_fee: Decimal = Decimal(0)
    extra_days: tuple[int, int] = (0, 0)
    label: str = ""


@dataclass
class Draft:
    mode: str
    lines: list[Line]
    origin_hub: str
    dest_hub: str
    summary: str
    days: tuple[int, int]
    co2: float
    countries: set[str] = field(default_factory=set)
    notes: list[str] = field(default_factory=list)

    @property
    def logistics_usd(self) -> Decimal:
        return sum((ln.usd for ln in self.lines if ln.stage != "goods"), Decimal(0))


class Data:
    def __init__(self):
        self.lanes = load_json("lanes.json")
        self.handling = load_json("handling.json")
        self.duties = load_json("duties.json")
        self.routes = load_json("routes.json")

    def region(self, cc: str) -> str:
        return self.lanes["regions"].get(cc, "EUR")

    def road_rate(self, cc: str) -> Decimal:
        r = self.handling["road_rate_per_km_usd"]
        return D(r.get(cc, r["default"]))


DATA = Data()


def haul_cost(cc: str, km: Decimal, kg: Decimal, m3: Decimal, containers: int | None = None) -> Decimal:
    rate, minimum = DATA.road_rate(cc), D(DATA.handling["road_min_haul_usd"])
    if containers:
        return max(minimum, km * rate) * containers
    trucks = cargo.containers_needed(cargo.TRUCK, kg, m3)
    factor = max(Decimal("0.3"), cargo.fill_ratio(cargo.TRUCK, kg, m3)) if trucks == 1 else Decimal(1)
    return max(minimum * factor, km * rate * trucks * factor)


def inland_days(km: Decimal) -> tuple[int, int]:
    return (0, 0) if km < 5 else (max(1, math.ceil(km / 600)), max(1, math.ceil(km / 400)))


def synth_lane(km: Decimal) -> dict:
    d = DATA.lanes["default"]
    f40 = D(d["sea_fcl_40_base"]) + D(d["sea_fcl_40_per_1000km"]) * km / 1000
    air = D(d["air_base_per_kg"]) + D(d["air_per_kg_per_1000km"]) * km / 1000
    days = max(5, math.ceil(float(km) / d["sea_km_per_day"]))
    return {"fcl_20": float(f40 * D("0.62")), "fcl_40": float(f40), "fcl_40hc": float(f40 * D("1.06")),
            "lcl_per_wm": float(f40 * D(d["lcl_ratio"])) + 15,
            "air_breaks": [[0, float(air * D("1.25"))], [100, float(air)], [500, float(air * D("0.8"))]],
            "air_min": d["air_min"], "air_surcharge_per_kg": 0.55, "rail_40": None,
            "sea_days": [days, days + 8], "air_days": d["air_days"], "rail_days": None, "synthetic": True}


def find_lane(o_region: str, d_region: str, km: Decimal) -> dict:
    lanes = DATA.lanes["lanes"]
    return lanes.get(f"{o_region}>{d_region}") or lanes.get(f"{d_region}>{o_region}") or synth_lane(km)


def air_rate_per_kg(lane: dict, chargeable: Decimal) -> Decimal:
    rate = D(lane["air_breaks"][0][1])
    for brk, r in lane["air_breaks"]:
        if chargeable >= D(brk):
            rate = D(r)
    return rate


class Engine:
    """One instance per request (holds request context and a distance cache)."""

    def __init__(self, geo: GeoClient, fx: FxService):
        self.geo, self.fx = geo, fx
        self._dist: dict = {}
        self.ctx: dict = {}

    async def dist(self, a: Point, b: Point, mode: str = "road") -> Decimal:
        key = (a, b, mode)
        if key not in self._dist:
            self._dist[key] = await self.geo.distance_km(a, b, mode)
        return self._dist[key]

    # ------------------------------------------------------------ public
    async def quote(self, req: LandedCostRequest) -> dict:
        disp = req.display_currency
        usd_rate, table = await self.fx.rate("USD", disp)
        g = req.goods
        oc, dc = req.origin.country_code, req.destination.country_code
        assumptions = [ASSUMPTION_TABLE]

        # goods value in USD
        val = g.total_value or (g.unit_price and MoneyIn(
            amount=g.unit_price.amount * g.quantity, currency=g.unit_price.currency))
        if val is None:
            raise ApiError("goods_value_required", "Provide goods.total_value or goods.unit_price", 422)
        v_rate, _ = await self.fx.rate(val.currency, "USD")
        goods_usd = val.amount * v_rate
        kg = g.total_weight_kg
        m3 = g.total_volume_m3
        if m3 is None:
            m3 = max(kg / D(250), D("0.01"))
            assumptions.append("Volume not given: estimated from weight at 250 kg/m3.")

        o_pt = await self._resolve(req.origin, "origin")
        d_pt = await self._resolve(req.destination, "destination")
        self.ctx = {"req": req, "kg": kg, "m3": m3, "goods_usd": goods_usd, "o_pt": o_pt, "d_pt": d_pt,
                    "oc": oc, "dc": dc, "stages": BUYER_STAGES[req.supplier_incoterm]}
        inc = req.supplier_incoterm
        if inc in ("CFR", "CIF", "DAP", "DDP", "FOB", "FCA"):
            assumptions.append(f"Supplier incoterm {inc}: stages already in the supplier price are "
                               "excluded from the totals; the named place is assumed to match the chosen hub.")
        if inc in ("CFR", "CIF", "DAP", "DDP"):
            assumptions.append("Main-leg freight is inside the supplier price, so other modes are indicative only.")
        assumptions.append("Recommended = lowest 0.6*cost + 0.4*time score (both normalised across options).")

        wanted = list(req.modes or ALL_MODES)
        explicit = req.modes is not None
        drafts: list[Draft] = []
        for mode in ALL_MODES:
            if mode not in wanted:
                continue
            reason = self._feasibility(mode, kg, m3, explicit, oc, dc)
            if reason:
                assumptions.append(f"{mode} not offered: {reason}.")
                continue
            d = await self._build_mode(mode)
            if d is None:
                assumptions.append(f"{mode} not offered: no usable hub/route found.")
            else:
                drafts.append(d)
        if not drafts:
            raise ApiError("no_feasible_option", "No feasible transport option for this shipment", 422)

        drafts.sort(key=lambda d: d.logistics_usd)
        rec = self._recommend(drafts)
        options = [self._render(d, goods_usd, val, disp, usd_rate, d is rec, g.dangerous_goods)
                   for d in drafts]
        quote_warn = []
        sw = sanctions_warning({oc, dc})
        if sw:
            quote_warn.append(sw)
        assumptions.append(f"FX: {table.source} rates as of {table.timestamp}; 1 USD = {usd_rate:.6g} {disp}.")
        return {"id": "qte_" + uuid.uuid4().hex, "currency": disp, "origin": req.origin.model_dump(exclude_none=True),
                "destination": req.destination.model_dump(exclude_none=True), "options": options,
                "assumptions": assumptions, "warnings": quote_warn, "created_at": utcnow_iso()}

    # ------------------------------------------------------------ helpers
    async def _resolve(self, loc, label: str) -> Point:
        if loc.point:
            return Point(loc.point.lat, loc.point.lon)
        p = await self.geo.resolve_city(loc.country_code, loc.city)
        if p is None and loc.city:
            p = await self.geo.resolve_city(loc.country_code, None)
        if p is None:
            raise ApiError("location_unresolved", f"Cannot resolve {label} location", 422,
                           {"country_code": loc.country_code, "city": loc.city})
        return p

    @staticmethod
    def _feasibility(mode, kg, m3, explicit, oc, dc) -> str | None:
        if mode == "sea_lcl" and (m3 > 30 or kg > 20000):
            return "too large for LCL (over 30 m3 / 20 t), use FCL"
        if mode == "air" and cargo.air_chargeable_kg(kg, m3) > 10000:
            return "chargeable weight over 10 t"
        if mode in ("rail", "sea_fcl_20", "sea_fcl_40", "sea_fcl_40hc") and not explicit:
            big = {"rail": (8, 5000), "sea_fcl_20": (8, 5000), "sea_fcl_40": (20, 20000),
                   "sea_fcl_40hc": (58.001, 40000)}[mode]
            if m3 < D(big[0]) and kg < D(big[1]):
                return f"cargo too small to justify it (needs ~{big[0]:.0f} m3 or {big[1]} kg)"
        if mode == "rail":
            lanes = DATA.lanes["lanes"]
            o_r, d_r = DATA.region(oc), DATA.region(dc)
            if not (lanes.get(f"{o_r}>{d_r}") or lanes.get(f"{d_r}>{o_r}") or {}).get("rail_40"):
                return "no rail service on this lane in the rate table"
        if mode == "road":
            cont = DATA.lanes["continents"]
            if cont.get(oc, "EA") != cont.get(dc, "EA"):
                return "no land connection between origin and destination"
        return None

    async def _sea_alts(self, dc: str, d_pt: Point) -> list[Alt]:
        alts: list[Alt] = []
        for r in DATA.routes["sea"].get(dc, []):
            hub = next((h for h in await self.geo.hubs(r["hub"][:2], "sea") if h.id == r["hub"]), None)
            via = None
            if r.get("via"):
                via = next((h for h in await self.geo.hubs(dc, "land") if h.id == r["via"]), None)
                if via is None:
                    continue
            if hub:
                alts.append(Alt(hub, via, D(r.get("border_fee", 0)), tuple(r.get("extra_days", (0, 0))),
                                r.get("label", hub.name)))
        for h in await self.geo.nearest_hubs(d_pt, "sea", 2, None):
            if all(a.hub.id != h.id for a in alts):
                foreign = h.country_code != dc
                alts.append(Alt(h, None, D(250) if foreign else D(0), (2, 4) if foreign else (0, 0), h.name))
        return alts

    async def _rail_alts(self, dc: str, d_pt: Point) -> list[Alt]:
        alts = []
        for r in DATA.routes["rail"].get(dc, []):
            hub = next((h for h in await self.geo.hubs(r["hub"][:2], "sea") if h.id == r["hub"]), None)
            via = next((h for h in await self.geo.hubs(dc, "land") if h.id == r.get("via")), None)
            if hub and via:
                alts.append(Alt(hub, via, D(r["border_fee"]), tuple(r["extra_days"]), r["label"]))
        if alts:
            return alts
        hubs = await self.geo.nearest_hubs(d_pt, "land", 1, dc) or await self.geo.nearest_hubs(d_pt, "sea", 1, dc)
        return [Alt(h, None, D(0), (0, 0), h.name) for h in hubs]

    async def _build_mode(self, mode: str) -> Draft | None:
        c = self.ctx
        if mode == "road":
            return await self._build(mode, None, None)
        fam = family(mode)
        if fam == "sea":
            o_hubs = await self.geo.nearest_hubs(c["o_pt"], "sea", 2, c["oc"])
            alts = await self._sea_alts(c["dc"], c["d_pt"])
        elif mode == "air":
            o_hubs = await self.geo.nearest_hubs(c["o_pt"], "air", 1, c["oc"])
            alts = [Alt(h, None, D(0), (0, 0), h.name)
                    for h in await self.geo.nearest_hubs(c["d_pt"], "air", 2, c["dc"])]
        else:  # rail
            o_hubs = [Hub("RAIL-" + c["oc"], "Origin rail terminal", "land", c["oc"], c["o_pt"].lat, c["o_pt"].lon)]
            alts = await self._rail_alts(c["dc"], c["d_pt"])
        best: Draft | None = None
        for oh in o_hubs:
            for alt in alts:
                d = await self._build(mode, oh, alt)
                if best is None or d.logistics_usd < best.logistics_usd:
                    best = d
        if best is None:
            return None
        # mention alternatives (cheapest of each other destination hub)
        others = []
        for alt in alts:
            if alt.hub.id != best.dest_hub:
                d = await self._build(mode, next(h for h in o_hubs if h.id == best.origin_hub), alt)
                delta = d.logistics_usd - best.logistics_usd
                others.append(f"{alt.label or alt.hub.name} ({'+' if delta >= 0 else '-'}USD {abs(delta):.0f})")
        if others:
            best.summary += " | alternatives: " + "; ".join(others)
        return best

    async def _build(self, mode: str, oh: Hub | None, alt: Alt | None) -> Draft:
        c, fam = self.ctx, family(mode)
        kg, m3, oc, dc = c["kg"], c["m3"], c["oc"], c["dc"]
        req: LandedCostRequest = c["req"]
        dg = req.goods.dangerous_goods
        h = DATA.handling
        o_reg, d_reg = DATA.region(oc), DATA.region(dc)
        src = "approx. rate table v1"
        spec = cargo.CONTAINERS.get(mode)
        n = cargo.containers_needed(spec, kg, m3) if spec else None
        lines: dict[str, Line] = {}
        days_min = days_max = 0
        countries = {oc, dc}
        ch_air = cargo.air_chargeable_kg(kg, m3)
        dgf = D(h["dg_factor"][fam]) if dg else Decimal(1)
        dg_txt = " (incl. DG surcharge)" if dg else ""
        oho, dho = h["origin"][o_reg], h["destination"][d_reg]

        if mode == "road":
            km = await self.dist(c["o_pt"], c["d_pt"], "road")
            trucks = cargo.containers_needed(cargo.TRUCK, kg, m3)
            ltl = max(Decimal("0.3"), cargo.fill_ratio(cargo.TRUCK, kg, m3)) if trucks == 1 else Decimal(1)
            rate = (DATA.road_rate(oc) + DATA.road_rate(dc)) / 2 * D("1.15")
            borders = 0 if oc == dc else max(1, round(float(km) / 2500))
            freight = (km * rate * trucks * ltl + D(h["border_fee_usd"]) * borders) * dgf
            lines["origin_handling"] = Line("origin_handling", "Export clearance and documents",
                                            D(oho["clearance"] + oho["docs"]), src)
            lines["main_leg"] = Line("main_leg", f"International truck {km:.0f} km x {trucks} truck(s)"
                                     f"{' (LTL)' if ltl < 1 else ''}, {borders} border crossing(s){dg_txt}", freight, src)
            lines["destination_handling"] = Line("destination_handling", "Import documents and handling",
                                                 D(dho["docs"]), src)
            days_min, days_max = 1 + math.ceil(float(km) / 700), 3 + math.ceil(float(km) / 450)
            days_min += borders
            days_max += borders * 2
            co2_km = km
            o_id, d_id = oc + "-road", dc + "-road"
            summary = f"Door-to-door by truck ({km:.0f} km)"
            main_km = km
        else:
            assert oh is not None and alt is not None
            o_id, d_id = oh.id, alt.hub.id
            countries |= {oh.country_code, alt.hub.country_code} | ({alt.via.country_code} if alt.via else set())
            # origin inland
            if mode == "rail":
                o_km = D(80)
            else:
                o_km = await self.dist(c["o_pt"], oh.point, "road")
            lines["origin_inland"] = Line("origin_inland", f"Truck from factory to {oh.name} ({o_km:.0f} km)",
                                          haul_cost(oc, o_km, kg, m3, n if fam in ("sea", "rail") and mode != "sea_lcl" else None), src)
            a, b = inland_days(o_km)
            days_min, days_max = a, b
            # origin handling
            if mode == "sea_lcl":
                oh_cost = D(oho["lcl_per_wm"]) * cargo.lcl_revenue_tons(kg, m3)
            elif fam == "sea":
                oh_cost = D(oho["thc_20" if mode == "sea_fcl_20" else "thc_40"]) * n
            elif mode == "air":
                oh_cost = max(D(oho["air_min"]), D(oho["air_per_kg"]) * ch_air)
            else:
                oh_cost = D(150) * n
            lines["origin_handling"] = Line("origin_handling", f"Terminal handling, export clearance and docs at {oh.name}",
                                            oh_cost + D(oho["clearance"] + oho["docs"]), src)
            # main leg
            main_mode = "air" if mode == "air" else "sea"
            main_km = await self.dist(oh.point, alt.hub.point, main_mode if mode != "rail" else "road")
            lane = find_lane(o_reg, d_reg, main_km)
            if mode == "sea_lcl":
                wm = cargo.lcl_revenue_tons(kg, m3)
                ml, desc = D(lane["lcl_per_wm"]) * wm, f"LCL {wm:.2f} W/M"
                dmin, dmax = lane["sea_days"][0] + 6, lane["sea_days"][1] + 10  # consolidation delay
            elif fam == "sea":
                key = {"sea_fcl_20": "fcl_20", "sea_fcl_40": "fcl_40", "sea_fcl_40hc": "fcl_40hc"}[mode]
                ml, desc = D(lane[key]) * n, f"{n} x {spec.key}' container"
                dmin, dmax = lane["sea_days"]
            elif mode == "air":
                rate = air_rate_per_kg(lane, ch_air)
                ml = max(D(lane["air_min"]), (rate + D(lane["air_surcharge_per_kg"])) * ch_air)
                desc = f"Air {ch_air:.0f} kg chargeable at {rate}/kg + surcharges"
                dmin, dmax = lane["air_days"]
            else:
                ml, desc = D(lane["rail_40"]) * n, f"{n} x 40' rail container"
                dmin, dmax = lane["rail_days"]
            lines["main_leg"] = Line("main_leg", f"{oh.name} to {alt.hub.name}: {desc}{dg_txt}", ml * dgf,
                                     src + (" (synthetic lane from distance)" if lane.get("synthetic") else ""))
            days_min += dmin
            days_max += dmax
            # destination handling
            if mode == "sea_lcl":
                dh = D(dho["lcl_per_wm"]) * cargo.lcl_revenue_tons(kg, m3)
            elif fam == "sea":
                dh = D(dho["thc_20" if mode == "sea_fcl_20" else "thc_40"]) * n
            elif mode == "air":
                dh = max(D(dho["air_min"]), D(dho["air_per_kg"]) * ch_air)
            else:
                dh = D(120) * n
            sur = DATA.routes.get("hub_surcharge", {}).get(alt.hub.id)
            if sur and fam == "sea":
                dh += D(sur["per_wm"]) * cargo.lcl_revenue_tons(kg, m3) if mode == "sea_lcl" else D(sur["per_container"]) * n
            lines["destination_handling"] = Line(
                "destination_handling", f"Terminal handling and delivery order at {alt.hub.name}"
                + (f" (incl. {sur['note']})" if sur and fam == "sea" else ""), dh + D(dho["docs"]), src)
            # destination inland
            cont = n if fam in ("sea", "rail") and mode != "sea_lcl" else None
            fee = alt.border_fee if cont else alt.border_fee * max(D("0.3"), cargo.fill_ratio(cargo.TRUCK, kg, m3))
            if alt.via:
                k1 = await self.dist(alt.hub.point, alt.via.point, "road")
                k2 = await self.dist(alt.via.point, c["d_pt"], "road")
                cost = (haul_cost(alt.hub.country_code, k1, kg, m3, cont) + haul_cost(dc, k2, kg, m3, cont)
                        + fee)
                km_tot = k1 + k2
                desc2 = f"Truck {alt.hub.name} -> {alt.via.name} -> destination ({km_tot:.0f} km) incl. border fee"
            else:
                km_tot = await self.dist(alt.hub.point, c["d_pt"], "road")
                cc = dc if alt.hub.country_code == dc else alt.hub.country_code
                cost = haul_cost(cc, km_tot, kg, m3, cont) + fee
                desc2 = f"Truck from {alt.hub.name} to destination ({km_tot:.0f} km)"
            lines["destination_inland"] = Line("destination_inland", desc2, cost, src)
            a, b = inland_days(km_tot)
            days_min += a + alt.extra_days[0]
            days_max += b + alt.extra_days[1]
            via_txt = f" + truck via {alt.via.name}" if alt.via else ""
            summary = f"{oh.name} -> {alt.hub.name} ({main_mode if mode != 'rail' else 'rail'}){via_txt} -> destination"
            co2_km = main_km
        # dwell / clearance time
        dw = {"sea": (3, 6), "air": (1, 2), "rail": (3, 5), "road": (0, 0)}[fam]
        cl = h["dest_clearance_days"].get(dc, h["dest_clearance_days"]["default"])
        days_min += dw[0] + cl[0]
        days_max += dw[1] + cl[1]

        # insurance
        goods_usd = c["goods_usd"]
        if req.insurance:
            ins = max(D(25), goods_usd * D("1.1") * D(INS_RATE[fam]))
            lines["insurance"] = Line("insurance", "Cargo insurance (110% of goods value)", ins, "approx. 0.2-0.35% premium")
        # duties
        stages = c["stages"]
        cv = goods_usd + sum((lines[s].usd for s in CUSTOMS_ADDS[req.supplier_incoterm] if s in lines), Decimal(0))
        rule = duty_rule(DATA.duties, dc, req.goods.hs_code, req.goods.category, oc)
        duty = cv * rule.duty_rate_pct / 100
        lines["duties"] = Line("duties", f"Import duty on customs value USD {cv:.0f}: {rule.rule}", duty,
                               "approx. duty table (verify with customs broker)")
        lines["taxes"] = Line("taxes", f"VAT/sales tax {rule.vat_pct}% on customs value + duty", (cv + duty) * rule.vat_pct / 100,
                              "approx. duty table (verify with customs broker)")
        lines["clearance"] = Line("clearance", "Customs broker / clearance fee", rule.clearance_fee_usd,
                                  "approx. duty table (verify with customs broker)")
        order = ["origin_inland", "origin_handling", "main_leg", "insurance", "destination_handling",
                 "duties", "taxes", "clearance", "destination_inland"]
        final = [lines[s] for s in order if s in lines and s in stages]
        co2_t = float(kg) / 1000
        co2 = co2_t * float(co2_km) * DATA.lanes["co2_kg_per_tonne_km"][fam]
        co2 += co2_t * 150 * DATA.lanes["co2_kg_per_tonne_km"]["road"]  # ~150 km inland trucking
        return Draft(mode, final, o_id, d_id, summary, (days_min, days_max), round(co2, 1), countries)

    # ------------------------------------------------------------ outputs
    @staticmethod
    def _recommend(drafts: list[Draft]) -> Draft:
        if len(drafts) == 1:
            return drafts[0]
        costs = [d.logistics_usd for d in drafts]
        times = [Decimal(d.days[0] + d.days[1]) / 2 for d in drafts]

        def norm(x, lo, hi):
            return (x - lo) / (hi - lo) if hi > lo else Decimal(0)
        scored = [(W_COST * norm(c, min(costs), max(costs)) + W_TIME * norm(t, min(times), max(times)), c, d)
                  for c, t, d in zip(costs, times, drafts, strict=True)]
        return min(scored, key=lambda s: (s[0], s[1]))[2]

    def _render(self, d: Draft, goods_usd: Decimal, goods_val, disp: str, rate: Decimal,
                recommended: bool, dg: bool) -> dict:
        lines_out, total, spread = [], Decimal(0), Decimal(0)
        raw = [Line("goods", "Goods price from supplier", goods_usd, "supplier quote", False)] + d.lines
        for ln in raw:
            amt = quantize(ln.usd * rate, disp)
            total += amt
            spread += quantize(amt * D(SPREAD[ln.stage]), disp) if ln.estimate else 0
            entry = {"stage": ln.stage, "description": ln.description, "amount": money(amt, disp),
                     "original_amount": money(ln.usd, "USD"), "fx_rate": f"{rate:.8g}",
                     "source": ln.source, "estimate": ln.estimate}
            if ln.stage == "goods":
                entry["original_amount"] = money(goods_val.amount, goods_val.currency)
            lines_out.append(entry)
        warns = cargo_warnings(d.mode, self.ctx["kg"], self.ctx["m3"], dg,
                               cargo.air_chargeable_kg(self.ctx["kg"], self.ctx["m3"]))
        warns += value_warnings(goods_usd, d.logistics_usd)
        sw = sanctions_warning(d.countries)
        if sw:
            warns.append(sw)
        return {"mode": d.mode, "origin_hub": d.origin_hub, "destination_hub": d.dest_hub,
                "route_summary": d.summary, "lines": lines_out,
                "total": {"min": money(total - spread, disp), "max": money(total + spread, disp)},
                "transit_days": {"min": d.days[0], "max": d.days[1]}, "co2_kg": d.co2,
                "recommended": recommended, "warnings": warns}
