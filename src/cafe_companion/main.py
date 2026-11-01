import logging
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Literal
from urllib.parse import urlparse

import httpx
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from . import gemini
from .config import settings
from .db import Base, SessionLocal, engine, get_db, utcnow
from .google_profile import BLOGGER_SCOPE, YT_SCOPE, fetch_blogs, fetch_userinfo, fetch_youtube, verify_token
from .models import Cafe, CheckIn, MenuItem, Order, OrderItem, User
from .security import current_user, issue_session, optional_user, require_staff
from .seed import seed
from .demo_guests import DEMO_PREFIX, remove_demo_guests, seed_demo_guests
from .waittime import ACTIVE, order_work_minutes, position_in_queue, simulate

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed(db)
        if settings.demo_guests and not settings.instance_connection_name:
            seed_demo_guests(db)
        else:
            remove_demo_guests(db)
    yield


app = FastAPI(title="Cafe Companion API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_list,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ================================================================== helpers
def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() + "Z" if dt else None


def get_cafe(db: Session, slug: str) -> Cafe:
    cafe = db.scalar(select(Cafe).where(Cafe.slug == slug))
    if not cafe:
        raise HTTPException(404, "Cafe not found")
    return cafe


def menu_dict(m: MenuItem) -> dict:
    return {
        "id": m.id, "name": m.name, "description": m.description, "category": m.category,
        "price_cents": m.price_cents, "prep_minutes": m.prep_minutes, "tags": m.tags or [], "available": m.available,
    }


def active_checkin(db: Session, user_id: int, cafe_id: int) -> CheckIn | None:
    return db.scalar(
        select(CheckIn).where(CheckIn.user_id == user_id, CheckIn.cafe_id == cafe_id, CheckIn.expires_at > utcnow())
    )


def public_profile(u: User, table_no: int | None = None) -> dict:
    """What *other* guests may see. Email is never included."""
    return {
        "id": u.id,
        "name": u.name,
        "picture": u.picture,
        "bio": u.bio,
        "table": table_no,
        "youtube": u.youtube if u.share_youtube else None,
        "blogs": u.blogs if u.share_blogs else None,
        "maps_url": u.maps_url if u.share_maps and u.maps_url else None,
        "demo": u.google_sub.startswith(DEMO_PREFIX),
    }


def ai_profile(p: dict) -> dict:
    """Trimmed profile sent to Gemini — first name + interests only."""
    yt = p.get("youtube")
    return {
        "id": p["id"],
        "name": p["name"].split()[0] if p["name"] else "Guest",
        "bio": p.get("bio") or "",
        "youtube": {"title": yt["title"], "description": yt["description"][:200], "recent": [v["title"] for v in yt.get("recent", [])]} if yt else None,
        "blogs": [{"name": b["name"], "recent": [x["title"] for x in b.get("recent", [])]} for b in p["blogs"]] if p.get("blogs") else None,
        "maps_contributor": bool(p.get("maps_url")),
    }


def me_dict(u: User) -> dict:
    return {**public_profile(u), "email": u.email, "share_youtube": u.share_youtube,
            "share_blogs": u.share_blogs, "share_maps": u.share_maps, "maps_url": u.maps_url}


def require_room_access(db: Session, user: User, cafe: Cafe) -> CheckIn:
    ci = active_checkin(db, user.id, cafe.id)
    if not ci:
        raise HTTPException(403, "Check in to this cafe to see who's here")
    if not ci.visible:
        raise HTTPException(403, "You're hidden. Make yourself visible to see others (it's a two-way street).")
    return ci


# ================================================================== health
@app.get("/healthz")
def healthz():
    return {"ok": True}


# ================================================================== auth & profile
class GoogleLogin(BaseModel):
    access_token: str


@app.post("/api/auth/google")
def google_login(body: GoogleLogin, db: Session = Depends(get_db)):
    with httpx.Client(timeout=10) as client:
        scopes = verify_token(client, body.access_token)
        info = fetch_userinfo(client, body.access_token)
        youtube = fetch_youtube(client, body.access_token) if YT_SCOPE in scopes else None
        blogs = fetch_blogs(client, body.access_token) if BLOGGER_SCOPE in scopes else None

    user = db.scalar(select(User).where(User.google_sub == info["sub"]))
    if not user:
        user = User(google_sub=info["sub"], email=info.get("email", ""), name=info.get("name") or "Guest")
        db.add(user)
    user.email = info.get("email", user.email)
    user.name = info.get("name") or user.name
    user.picture = info.get("picture", "")
    user.youtube = youtube
    user.blogs = blogs or None
    db.commit()
    return {"token": issue_session(user.id), "user": me_dict(user)}


@app.get("/api/me")
def get_me(user: User = Depends(current_user)):
    return me_dict(user)


class ProfileUpdate(BaseModel):
    bio: str | None = Field(None, max_length=280)
    maps_url: str | None = Field(None, max_length=500)
    share_youtube: bool | None = None
    share_blogs: bool | None = None
    share_maps: bool | None = None


MAPS_HOSTS = {"www.google.com", "google.com", "maps.google.com", "maps.app.goo.gl", "goo.gl"}


@app.patch("/api/me")
def update_me(body: ProfileUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if body.maps_url is not None:
        url = body.maps_url.strip()
        if url:
            p = urlparse(url)
            if p.scheme != "https" or p.hostname not in MAPS_HOSTS:
                raise HTTPException(400, "Paste your Google Maps contributor link (https://www.google.com/maps/contrib/…)")
        user.maps_url = url
    for field in ("bio", "share_youtube", "share_blogs", "share_maps"):
        val = getattr(body, field)
        if val is not None:
            setattr(user, field, val.strip() if isinstance(val, str) else val)
    db.commit()
    return me_dict(user)


@app.delete("/api/me")
def delete_me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.execute(delete(CheckIn).where(CheckIn.user_id == user.id))
    db.delete(user)
    db.commit()
    return {"deleted": True}


# ================================================================== cafe & menu
@app.get("/api/cafes/{slug}")
def cafe_info(slug: str, db: Session = Depends(get_db)):
    cafe = get_cafe(db, slug)
    _, eta = simulate(db, cafe.id, extra_work=4)
    wait = max(0, round((eta - utcnow()).total_seconds() / 60)) if eta else 0
    here = db.query(CheckIn).filter(CheckIn.cafe_id == cafe.id, CheckIn.expires_at > utcnow(), CheckIn.visible).count()
    return {
        "slug": cafe.slug, "name": cafe.name, "tagline": cafe.tagline, "currency": cafe.currency,
        "table_count": cafe.table_count, "wait_minutes": wait, "people_here": here,
        "menu": [menu_dict(m) for m in cafe.menu],
    }


class RecommendIn(BaseModel):
    mood: str = Field(..., min_length=1, max_length=300)


@app.post("/api/cafes/{slug}/recommend")
def recommend(slug: str, body: RecommendIn, db: Session = Depends(get_db)):
    cafe = get_cafe(db, slug)
    menu = [menu_dict(m) for m in cafe.menu if m.available]
    _, eta = simulate(db, cafe.id, extra_work=4)
    wait = max(0, round((eta - utcnow()).total_seconds() / 60)) if eta else 0
    return gemini.recommend(body.mood, [{k: m[k] for k in ("id", "name", "description", "category", "prep_minutes", "tags")} for m in menu], wait)


# ================================================================== ordering & wait time
class OrderLine(BaseModel):
    menu_item_id: int
    qty: int = Field(..., ge=1, le=20)


class OrderIn(BaseModel):
    table: int = Field(..., ge=1)
    items: list[OrderLine] = Field(..., min_length=1, max_length=30)
    note: str = Field("", max_length=280)


def order_dict(db: Session, o: Order) -> dict:
    eta = None
    if o.status in ACTIVE:
        etas, _ = simulate(db, o.cafe_id)
        eta = etas.get(o.id)
    return {
        "id": o.id, "token": o.token, "table": o.table_no, "status": o.status, "note": o.note,
        "total_cents": o.total_cents, "created_at": iso(o.created_at), "ready_at": iso(o.ready_at),
        "eta": iso(eta),
        "eta_minutes": max(0, round((eta - utcnow()).total_seconds() / 60)) if eta else 0,
        "position": position_in_queue(db, o) if o.status in ACTIVE else 0,
        "items": [{"name": i.name, "qty": i.qty, "price_cents": i.price_cents} for i in o.items],
    }


@app.post("/api/cafes/{slug}/orders")
def place_order(slug: str, body: OrderIn, user: User | None = Depends(optional_user), db: Session = Depends(get_db)):
    cafe = get_cafe(db, slug)
    if body.table > cafe.table_count:
        raise HTTPException(400, "Unknown table")
    menu = {m.id: m for m in cafe.menu}
    order = Order(cafe_id=cafe.id, table_no=body.table, user_id=user.id if user else None,
                  token=secrets.token_urlsafe(18), note=body.note.strip(), total_cents=0,
                  status="placed", created_at=utcnow())
    preps: list[int] = []
    for line in body.items:
        m = menu.get(line.menu_item_id)
        if not m or not m.available:
            raise HTTPException(400, f"Item {line.menu_item_id} is not available")
        order.items.append(OrderItem(menu_item_id=m.id, name=m.name, price_cents=m.price_cents, qty=line.qty))
        order.total_cents += m.price_cents * line.qty
        preps += [m.prep_minutes] * line.qty
    order.work_minutes = order_work_minutes(preps)
    db.add(order)
    db.commit()
    return order_dict(db, order)


@app.get("/api/orders/{token}")
def track_order(token: str, db: Session = Depends(get_db)):
    o = db.scalar(select(Order).where(Order.token == token).options(selectinload(Order.items)))
    if not o:
        raise HTTPException(404, "Order not found")
    return order_dict(db, o)


# ---- staff (barista screen)
@app.get("/api/cafes/{slug}/staff/orders", dependencies=[Depends(require_staff)])
def staff_orders(slug: str, db: Session = Depends(get_db)):
    cafe = get_cafe(db, slug)
    since = utcnow() - timedelta(hours=12)
    orders = db.scalars(
        select(Order).where(Order.cafe_id == cafe.id, (Order.status.in_(ACTIVE + ("ready",))) | (Order.created_at > since))
        .options(selectinload(Order.items)).order_by(Order.created_at)
    ).all()
    etas, _ = simulate(db, cafe.id)
    return [
        {"id": o.id, "table": o.table_no, "status": o.status, "note": o.note, "created_at": iso(o.created_at),
         "eta": iso(etas.get(o.id)), "items": [{"name": i.name, "qty": i.qty} for i in o.items]}
        for o in orders if o.status != "served" or o.created_at > since
    ]


class StatusIn(BaseModel):
    status: Literal["placed", "preparing", "ready", "served", "cancelled"]


@app.post("/api/cafes/{slug}/staff/orders/{order_id}", dependencies=[Depends(require_staff)])
def staff_set_status(slug: str, order_id: int, body: StatusIn, db: Session = Depends(get_db)):
    cafe = get_cafe(db, slug)
    o = db.get(Order, order_id)
    if not o or o.cafe_id != cafe.id:
        raise HTTPException(404, "Order not found")
    o.status = body.status
    if body.status == "preparing" and not o.started_at:
        o.started_at = utcnow()
    if body.status == "ready":
        o.ready_at = utcnow()
    db.commit()
    return {"ok": True}


# ================================================================== the room (connect people)
class CheckInIn(BaseModel):
    table: int = Field(..., ge=1)
    visible: bool = True


@app.post("/api/cafes/{slug}/checkin")
def check_in(slug: str, body: CheckInIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    cafe = get_cafe(db, slug)
    ci = active_checkin(db, user.id, cafe.id)
    if not ci:
        ci = CheckIn(user_id=user.id, cafe_id=cafe.id, table_no=body.table, checked_in_at=utcnow(),
                     expires_at=utcnow())
        db.add(ci)
    ci.table_no = body.table
    ci.visible = body.visible
    ci.expires_at = utcnow() + timedelta(hours=settings.checkin_hours)
    db.commit()
    return {"table": ci.table_no, "visible": ci.visible, "expires_at": iso(ci.expires_at)}


@app.get("/api/cafes/{slug}/checkin")
def my_checkin(slug: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ci = active_checkin(db, user.id, get_cafe(db, slug).id)
    return {"table": ci.table_no, "visible": ci.visible, "expires_at": iso(ci.expires_at)} if ci else None


@app.delete("/api/cafes/{slug}/checkin")
def check_out(slug: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    cafe = get_cafe(db, slug)
    db.execute(delete(CheckIn).where(CheckIn.user_id == user.id, CheckIn.cafe_id == cafe.id))
    db.commit()
    return {"ok": True}


def visible_people(db: Session, cafe: Cafe, exclude_user: int | None = None) -> list[dict]:
    rows = db.scalars(
        select(CheckIn).where(CheckIn.cafe_id == cafe.id, CheckIn.visible, CheckIn.expires_at > utcnow())
        .options(selectinload(CheckIn.user)).order_by(CheckIn.checked_in_at.desc())
    ).all()
    return [public_profile(c.user, c.table_no) for c in rows if c.user_id != exclude_user]


@app.get("/api/cafes/{slug}/people")
def people(slug: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    cafe = get_cafe(db, slug)
    require_room_access(db, user, cafe)
    return visible_people(db, cafe, exclude_user=user.id)


@app.get("/api/cafes/{slug}/people/{user_id}")
def person(slug: str, user_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    cafe = get_cafe(db, slug)
    require_room_access(db, user, cafe)
    ci = active_checkin(db, user_id, cafe.id)
    if not ci or not ci.visible:
        raise HTTPException(404, "This person isn't visible here right now")
    return public_profile(ci.user, ci.table_no)


@app.get("/api/cafes/{slug}/room")
def room(slug: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    cafe = get_cafe(db, slug)
    require_room_access(db, user, cafe)
    everyone = visible_people(db, cafe)
    return {"count": len(everyone), **gemini.room_vibe(cafe.name, [ai_profile(p) for p in everyone])}


@app.get("/api/cafes/{slug}/people/{user_id}/icebreaker")
def icebreaker(slug: str, user_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    them = person(slug, user_id, user, db)
    return gemini.icebreaker(ai_profile(public_profile(user)), ai_profile(them))
