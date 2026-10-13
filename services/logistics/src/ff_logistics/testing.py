"""Request builder used by tests."""


def req(origin=("CN", "Shanghai"), dest=("IQ", "Baghdad"), kg=18000, m3=60, value="40000", inc="EXW", **kw):
    body = {"goods": {"description": "test goods", "quantity": "1000", "total_weight_kg": str(kg),
                      "total_volume_m3": str(m3), "total_value": {"amount": value, "currency": "USD"},
                      "category": "machinery"},
            "origin": {"country_code": origin[0], "city": origin[1]},
            "destination": {"country_code": dest[0], "city": dest[1]}, "supplier_incoterm": inc}
    body.update(kw)
    return body
