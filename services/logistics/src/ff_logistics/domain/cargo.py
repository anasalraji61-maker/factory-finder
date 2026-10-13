"""Chargeable weight and container fitting (pure)."""
import math
from dataclasses import dataclass
from decimal import Decimal

from .money import D

AIR_KG_PER_M3 = Decimal(167)
LCL_KG_PER_M3 = Decimal(1000)


@dataclass(frozen=True)
class ContainerSpec:
    key: str
    volume_m3: Decimal
    max_kg: Decimal


CONTAINERS = {
    "sea_fcl_20": ContainerSpec("20", D(28), D(25000)),
    "sea_fcl_40": ContainerSpec("40", D(58), D(26000)),
    "sea_fcl_40hc": ContainerSpec("40hc", D(68), D(26000)),
    "rail": ContainerSpec("40", D(58), D(26000)),
}
TRUCK = ContainerSpec("truck", D(60), D(24000))


def air_chargeable_kg(kg: Decimal, m3: Decimal) -> Decimal:
    return max(D(kg), D(m3) * AIR_KG_PER_M3)


def lcl_revenue_tons(kg: Decimal, m3: Decimal) -> Decimal:
    """LCL W/M: 1 m3 = 1000 kg, billed on the greater of tonnes or m3, minimum 1."""
    return max(Decimal(1), D(m3), D(kg) / LCL_KG_PER_M3)


def containers_needed(spec: ContainerSpec, kg: Decimal, m3: Decimal) -> int:
    return max(1, math.ceil(D(m3) / spec.volume_m3), math.ceil(D(kg) / spec.max_kg))


def fill_ratio(spec: ContainerSpec, kg: Decimal, m3: Decimal) -> Decimal:
    n = containers_needed(spec, kg, m3)
    return max(D(m3) / (spec.volume_m3 * n), D(kg) / (spec.max_kg * n))
