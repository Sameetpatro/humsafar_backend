# app/routers/store.py
# Coupon store. Users spend gems to buy a discount coupon from a partner
# (a hotel/restaurant Recommendation). The "two spinning wheels" on the client
# are cosmetic — the SERVER decides the partner and the discount % so gem costs
# can't be gamed. The coupon deadline is derived from the user's distance to the
# partner at purchase time.

import random
import string
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Recommendation, UserCoupon
from app.routers.users import get_user_uuid
from app.schemas import (
    StorePartner,
    CouponPurchaseRequest,
    CouponResponse,
    CouponPurchaseResponse,
)
from app.services import gems
from app.utils import haversine

router = APIRouter(prefix="/store", tags=["Store"])

# tier -> (gem price, (min discount %, max discount %))
TIERS = {
    "ultimate": (200, (20, 30)),
    "special":  (120, (12, 19)),
    "normal":   (70,  (7, 11)),
}

PARTNER_KINDS = {"hotel", "restaurant"}


def _deadline_hours(distance_meters: float | None) -> float:
    """<5km -> 1.5h, 5-10km -> 2.5h, otherwise 3.5h (unknown distance -> 2.5h)."""
    if distance_meters is None:
        return 2.5
    km = distance_meters / 1000.0
    if km < 5:
        return 1.5
    if km <= 10:
        return 2.5
    return 3.5


def _new_code() -> str:
    return "DS-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))


def _coupon_status(c: UserCoupon, now: datetime) -> str:
    if c.status == "redeemed":
        return "redeemed"
    if c.expires_at and c.expires_at <= now:
        return "expired"
    return c.status


@router.get("/partners", response_model=list[StorePartner])
def list_partners(
    site_id: int | None = None,
    kind: str = "hotel",
    user_lat: float | None = None,
    user_lng: float | None = None,
    db: Session = Depends(get_db),
):
    if kind not in PARTNER_KINDS:
        raise HTTPException(status_code=400, detail="kind must be 'hotel' or 'restaurant'")

    q = db.query(Recommendation).filter(Recommendation.type == kind)
    if site_id is not None:
        q = q.filter(Recommendation.site_id == site_id)
    rows = q.all()

    out = []
    for r in rows:
        dist = None
        if user_lat is not None and user_lng is not None and r.latitude is not None and r.longitude is not None:
            dist = round(haversine(user_lat, user_lng, r.latitude, r.longitude), 1)
        out.append(StorePartner(
            id=r.id, name=r.name, type=r.type, description=r.description,
            latitude=r.latitude, longitude=r.longitude, distance_meters=dist,
        ))
    out.sort(key=lambda p: (p.distance_meters is None, p.distance_meters or 0))
    return out


@router.post("/purchase", response_model=CouponPurchaseResponse)
def purchase_coupon(req: CouponPurchaseRequest, db: Session = Depends(get_db)):
    if req.tier not in TIERS:
        raise HTTPException(status_code=400, detail="Invalid tier")
    if req.partner_kind not in PARTNER_KINDS:
        raise HTTPException(status_code=400, detail="partner_kind must be 'hotel' or 'restaurant'")

    user_uuid = get_user_uuid(req.firebase_uid, db)
    price, (lo, hi) = TIERS[req.tier]

    if gems.get_balance(db, user_uuid) < price:
        raise HTTPException(status_code=402, detail="Not enough gems")

    q = db.query(Recommendation).filter(Recommendation.type == req.partner_kind)
    if req.site_id is not None:
        q = q.filter(Recommendation.site_id == req.site_id)
    partners = q.all()
    if not partners:
        raise HTTPException(status_code=404, detail=f"No {req.partner_kind} partners available")

    # Server-side spin: random partner + random discount within the tier band.
    partner = random.choice(partners)
    discount = random.randint(lo, hi)

    distance = None
    if (req.user_lat is not None and req.user_lng is not None
            and partner.latitude is not None and partner.longitude is not None):
        distance = round(haversine(req.user_lat, req.user_lng, partner.latitude, partner.longitude), 1)

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=_deadline_hours(distance))

    # Unique-ish code (retry a couple of times on collision).
    code = _new_code()
    for _ in range(5):
        if not db.query(UserCoupon).filter(UserCoupon.code == code).first():
            break
        code = _new_code()

    try:
        new_balance = gems.debit(db, user_uuid, price, reason="coupon_purchase",
                                 ref_id=code, commit=False)
    except ValueError:
        db.rollback()
        raise HTTPException(status_code=402, detail="Not enough gems")

    coupon = UserCoupon(
        user_id=user_uuid,
        recommendation_id=partner.id,
        partner_name=partner.name,
        partner_type=partner.type,
        partner_lat=partner.latitude,
        partner_lng=partner.longitude,
        site_id=req.site_id,
        tier=req.tier,
        discount_pct=discount,
        gems_spent=price,
        code=code,
        status="active",
        distance_meters=distance,
        expires_at=expires_at,
    )
    db.add(coupon)
    db.commit()
    db.refresh(coupon)

    return CouponPurchaseResponse(
        coupon=CouponResponse.model_validate(coupon),
        new_balance=new_balance,
    )


@router.get("/coupons/{firebase_uid}", response_model=list[CouponResponse])
def my_coupons(firebase_uid: str, db: Session = Depends(get_db)):
    user_uuid = get_user_uuid(firebase_uid, db)
    now = datetime.now(timezone.utc)
    rows = (
        db.query(UserCoupon)
        .filter(UserCoupon.user_id == user_uuid)
        .order_by(UserCoupon.created_at.desc())
        .all()
    )
    out = []
    for c in rows:
        resp = CouponResponse.model_validate(c)
        resp.status = _coupon_status(c, now)
        out.append(resp)
    return out
