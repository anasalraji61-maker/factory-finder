"""Profile endpoints and home feed."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ff_gateway.api.deps import current_user, internal_headers, to_me
from ff_gateway.db import User
from ff_gateway.domain.errors import AccountExists, SupplierClaimed, ValidationFailed
from ff_gateway.schemas import MeOut, MePatch

router = APIRouter(tags=["me"])


@router.get("/v1/me", response_model=MeOut)
async def get_me(user: User = Depends(current_user)) -> MeOut:
    return to_me(user)


@router.patch("/v1/me", response_model=MeOut)
async def patch_me(body: MePatch, request: Request, user: User = Depends(current_user)) -> MeOut:
    data = body.model_dump(exclude_unset=True)
    if "name" in data and data["name"] is None:
        raise ValidationFailed.for_field("name", "name cannot be null")
    for required in ("role", "display_currency", "language"):
        if required in data and data[required] is None:
            raise ValidationFailed.for_field(required, f"{required} cannot be null")
    async with request.app.state.sessionmaker() as s:
        db_user = await s.get(User, user.id)
        assert db_user is not None
        for field in ("email", "phone"):
            changed = bool(data.get(field)) and data[field] != getattr(db_user, field)
            if changed and await s.scalar(select(User).where(getattr(User, field) == data[field])):
                raise AccountExists(field)
        sid = data.get("supplier_id")
        if sid and sid != db_user.supplier_id:
            holder = await s.scalar(select(User).where(User.supplier_id == sid))
            if holder is not None and holder.id != db_user.id:
                raise SupplierClaimed()
        if (
            "email" in data and data["email"] is None and not (db_user.phone or data.get("phone"))
        ) or (
            "phone" in data and data["phone"] is None and not (db_user.email or data.get("email"))
        ):
            raise ValidationFailed.for_field(
                "email", "an account needs at least one of email or phone"
            )
        if "supplier_id" in data:
            if sid is None:  # release
                db_user.supplier_claim_status = "none"
            elif sid != db_user.supplier_id:  # new claim: never trusted until an admin approves it
                db_user.supplier_claim_status = "pending"
        for k, v in data.items():
            setattr(
                db_user,
                k,
                body.default_destination.model_dump(exclude_none=True)
                if k == "default_destination" and v is not None
                else v,
            )
        try:
            await s.commit()
        except IntegrityError as e:
            await s.rollback()
            if sid:
                raise SupplierClaimed() from e
            raise AccountExists() from e
        return to_me(db_user)


@router.get("/v1/home")
async def home(request: Request, user: User = Depends(current_user)) -> dict:
    dest = (user.default_destination or {}).get("country_code")
    feed = await request.app.state.home_client.fetch(
        display_currency=user.display_currency, destination_country=dest,
        headers=internal_headers(request, user.id),
    )  # fmt: skip
    return {"user": {"id": user.id, "name": user.name, "language": user.language}, **feed}
