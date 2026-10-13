from ..domain.duties import load_json
from ..domain.engine import DATA


def list_carriers(origin_country: str | None, destination_country: str | None, mode: str | None) -> list[dict]:
    o = DATA.region(origin_country) if origin_country else None
    d = DATA.region(destination_country) if destination_country else None
    out = []
    for c in load_json("carriers.json")["carriers"]:
        if mode and mode not in c["modes"]:
            continue
        if o and "*" not in c["origin_regions"] and o not in c["origin_regions"]:
            continue
        if d and "*" not in c["destination_regions"] and d not in c["destination_regions"]:
            continue
        out.append(c)
    return sorted(out, key=lambda c: -c["rating"])
