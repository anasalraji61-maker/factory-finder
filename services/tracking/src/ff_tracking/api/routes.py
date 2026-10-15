"""Thin FastAPI routers."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Path, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ff_tracking.domain.carriers import find_carrier
from ff_tracking.domain.directory import suggest_carrier
from ff_tracking.domain.enums import ReferenceType, ShipmentStatus, TransportMode
from ff_tracking.domain.errors import Unauthenticated
from ff_tracking.domain.models import Shipment
from ff_tracking.domain.progress import progress_percent
from ff_tracking.domain.validators import strip_control, validate_reference
from ff_tracking.service import ShipmentService, detect_carrier

router = APIRouter(prefix="/v1")


class ShipmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reference: str = Field(min_length=3, max_length=64)
    reference_type: ReferenceType
    carrier: str | None = Field(default=None, max_length=80)
    label: str | None = Field(default=None, max_length=120)

    @field_validator("carrier", "label", mode="before")
    @classmethod
    def _no_control_chars(cls, v: object) -> object:
        return strip_control(v) if isinstance(v, str) else v


def current_user(x_user_id: Annotated[str | None, Header()] = None) -> str:
    if not x_user_id or not x_user_id.strip():
        raise Unauthenticated("X-User-Id header is required")
    return x_user_id.strip()


def service(request: Request) -> ShipmentService:
    return request.app.state.service


User = Annotated[str, Depends(current_user)]
Svc = Annotated[ShipmentService, Depends(service)]


def present(sh: Shipment) -> dict[str, Any]:
    data = sh.model_dump(mode="json")
    data["mode"] = sh.mode.value
    data["progress_percent"] = progress_percent(sh.status, sh.events)
    return data


@router.post("/shipments", status_code=201)
async def create_shipment(body: ShipmentCreate, user: User, svc: Svc) -> dict[str, Any]:
    return present(await svc.create(user, body.reference, body.reference_type, body.carrier, body.label))


@router.get("/shipments")
async def list_shipments(
    user: User, svc: Svc, status: ShipmentStatus | None = None,
    page: Annotated[int, Query(ge=1)] = 1, page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict[str, Any]:
    items, total = await svc.list(user, status.value if status else None, page, page_size)
    return {"items": [present(s) for s in items], "total": total, "page": page, "page_size": page_size}


@router.get("/shipments/{shipment_id}")
async def get_shipment(shipment_id: str, user: User, svc: Svc) -> dict[str, Any]:
    return present(await svc.get(user, shipment_id))


@router.post("/shipments/{shipment_id}/refresh")
async def refresh_shipment(shipment_id: str, user: User, svc: Svc) -> dict[str, Any]:
    return present(await svc.refresh(user, shipment_id))


@router.delete("/shipments/{shipment_id}", status_code=204)
async def delete_shipment(shipment_id: str, user: User, svc: Svc) -> Response:
    await svc.delete(user, shipment_id)
    return Response(status_code=204)


@router.get("/validate/{reference_type}/{reference}")
async def validate(reference_type: ReferenceType, reference: Annotated[str, Path(min_length=1, max_length=64)]) -> dict[str, Any]:
    v = validate_reference(reference_type, reference)
    carrier = detect_carrier(reference_type, v.prefix, None) if v.valid else None
    suggestion = suggest_carrier(reference_type, v.prefix) if v.valid else None
    return {
        "reference": reference, "reference_type": reference_type.value, "valid": v.valid,
        "normalized": v.normalized, "reason": v.reason,
        "mode": reference_type.mode.value if isinstance(reference_type.mode, TransportMode) else None,
        "carrier": carrier.model_dump(mode="json") if carrier else None,
        "suggestions": list(v.suggestions),
        "carrier_suggestion": suggestion.to_dict() if suggestion else None,
    }


__all__ = ["find_carrier", "router"]
