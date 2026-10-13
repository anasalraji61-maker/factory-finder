"""Which cost stages the BUYER pays on top of the supplier price, per incoterm."""

BUYER_STAGES: dict[str, frozenset[str]] = {
    "EXW": frozenset({"origin_inland", "origin_handling", "main_leg", "insurance",
                      "destination_handling", "duties", "taxes", "clearance", "destination_inland"}),
    "FCA": frozenset({"origin_handling", "main_leg", "insurance", "destination_handling",
                      "duties", "taxes", "clearance", "destination_inland"}),
    "FOB": frozenset({"main_leg", "insurance", "destination_handling", "duties", "taxes",
                      "clearance", "destination_inland"}),
    "CFR": frozenset({"insurance", "destination_handling", "duties", "taxes", "clearance",
                      "destination_inland"}),
    "CIF": frozenset({"destination_handling", "duties", "taxes", "clearance", "destination_inland"}),
    "DAP": frozenset({"duties", "taxes", "clearance"}),
    "DDP": frozenset(),
}

# customs value = goods price + the freight/insurance the buyer pays before import
CUSTOMS_ADDS: dict[str, frozenset[str]] = {
    "EXW": frozenset({"origin_inland", "origin_handling", "main_leg", "insurance"}),
    "FCA": frozenset({"origin_handling", "main_leg", "insurance"}),
    "FOB": frozenset({"main_leg", "insurance"}),
    "CFR": frozenset({"insurance"}),
    "CIF": frozenset(),
    "DAP": frozenset(),
    "DDP": frozenset(),
}
