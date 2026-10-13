from decimal import Decimal

SANCTIONED = {"IR", "SY", "KP", "CU", "RU"}


def sanctions_warning(countries: set[str]) -> str | None:
    hit = sorted(countries & SANCTIONED)
    if not hit:
        return None
    return (f"Sanctions/export-control: lane touches {', '.join(hit)}. Verify licensing, "
            "banking and carrier acceptance before shipping (warning only, not legal advice).")


def cargo_warnings(mode: str, kg: Decimal, m3: Decimal, dg: bool, chargeable_air: Decimal) -> list[str]:
    w = []
    if dg:
        if mode == "air":
            w.append("Dangerous goods by air: needs IATA DGR paperwork; many airlines refuse "
                     "them and a DG surcharge is applied.")
        else:
            w.append("Dangerous goods: needs IMDG/ADR declaration and carrier acceptance; "
                     "DG surcharge applied.")
    if mode == "sea_lcl" and (m3 > 15 or kg > 12000):
        w.append("Large for LCL (over 15 m3 / 12 t): consider FCL; LCL space and schedule may not be guaranteed.")
    if mode == "air" and chargeable_air > 3000:
        w.append("Heavy/bulky for air freight (chargeable over 3 t): may need freighter and early booking.")
    return w


def value_warnings(goods_usd: Decimal, logistics_usd: Decimal) -> list[str]:
    w = []
    if goods_usd < 1000:
        w.append("Very low goods value (under USD 1,000): fixed fees dominate; consider consolidating.")
    if goods_usd > 0 and logistics_usd > goods_usd:
        pct = (logistics_usd / goods_usd * 100).quantize(Decimal(1))
        w.append(f"Logistics and fees are {pct}% of the goods value.")
    return w
