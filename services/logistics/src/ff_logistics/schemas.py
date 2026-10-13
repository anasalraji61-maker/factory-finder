from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

Incoterm = Literal["EXW", "FCA", "FOB", "CFR", "CIF", "DAP", "DDP"]
Mode = Literal["sea_lcl", "sea_fcl_20", "sea_fcl_40", "sea_fcl_40hc", "air", "rail", "road"]
ALL_MODES: list[str] = ["sea_lcl", "sea_fcl_20", "sea_fcl_40", "sea_fcl_40hc", "air", "rail", "road"]


class MoneyIn(BaseModel):
    amount: Decimal = Field(ge=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")


class GeoPointIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class LocationIn(BaseModel):
    country_code: str = Field(pattern=r"^[A-Z]{2}$")
    city: str | None = None
    point: GeoPointIn | None = None


class GoodsIn(BaseModel):
    listing_id: str | None = None
    description: str = ""
    quantity: Decimal = Field(default=Decimal(1), gt=0)
    unit: str = "pcs"
    total_value: MoneyIn | None = None
    unit_price: MoneyIn | None = None
    total_weight_kg: Decimal = Field(gt=0)
    total_volume_m3: Decimal | None = Field(default=None, gt=0)
    hs_code: str | None = None
    category: str | None = None
    dangerous_goods: bool = False


class LandedCostRequest(BaseModel):
    goods: GoodsIn
    origin: LocationIn
    destination: LocationIn
    supplier_incoterm: Incoterm = "EXW"
    modes: list[Mode] | None = None
    display_currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    insurance: bool = True


class ConvertRequest(BaseModel):
    model_config = {"populate_by_name": True}
    amount: Decimal
    from_currency: str = Field(alias="from", pattern=r"^[A-Z]{3}$")
    to_currency: str = Field(alias="to", pattern=r"^[A-Z]{3}$")
