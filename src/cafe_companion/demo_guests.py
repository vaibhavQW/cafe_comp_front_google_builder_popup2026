"""Fake guests checked in to the demo cafe, so the room isn't empty during local testing.

Enabled only with DEMO_GUESTS=true, and never when connected to Cloud SQL.
All links point at example.com so nobody real is ever referenced.
"""

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import utcnow
from .models import Cafe, CheckIn, User

DEMO_PREFIX = "demo-"


def _avatar(seed: str) -> str:
    return f"https://api.dicebear.com/9.x/notionists/svg?seed={seed}&backgroundColor=f4e3d5"


def _thumb(seed: str) -> str:
    return f"https://picsum.photos/seed/{seed}/320/180"


def _yt(handle: str, title: str, desc: str, subs: int, videos: list[str]) -> dict:
    return {
        "channel_id": f"UC-demo-{handle}",
        "title": title,
        "description": desc,
        "thumbnail": _avatar(handle),
        "url": f"https://example.com/youtube/{handle}",
        "subscribers": subs,
        "videos": len(videos) * 12,
        "views": subs * 37,
        "recent": [
            {"title": v, "url": f"https://example.com/youtube/{handle}/{i}", "thumbnail": _thumb(f"{handle}{i}"),
             "published_at": "2026-10-2%dT10:00:00Z" % i}
            for i, v in enumerate(videos)
        ],
    }


def _blog(slug: str, name: str, posts: list[str], total: int) -> dict:
    return {
        "name": name,
        "url": f"https://example.com/blog/{slug}",
        "post_count": total,
        "recent": [{"title": p, "url": f"https://example.com/blog/{slug}/{i}", "published_at": "2026-10-15T09:00:00Z"}
                   for i, p in enumerate(posts)],
    }


GUESTS = [
    dict(key="asha", name="Asha Rao", table=2, bio="Travel vlogger, editing my Ladakh series here today",
         youtube=_yt("asha", "Asha on the Road", "Slow travel across India on a budget.", 48200,
                     ["Ladakh in 10 days on ₹25k", "Spiti winter drive gone wrong", "Best cafés in Old Manali"]),
         blogs=None, maps=True),
    dict(key="rohan", name="Rohan Mehta", table=5, bio="Backend dev. Ask me about Postgres 🐘",
         youtube=None,
         blogs=[_blog("rohan", "Query Plans & Coffee", ["Why your index isn't used", "Cloud SQL vs self-hosted Postgres", "FastAPI in production"], 64)],
         maps=False),
    dict(key="meera", name="Meera Iyer", table=5, bio="Food photographer · Local Guide level 8",
         youtube=_yt("meera", "Meera Eats", "Short food reels from Bangalore and beyond.", 3100,
                     ["The perfect filter coffee", "₹100 street food challenge"]),
         blogs=None, maps=True),
    dict(key="kabir", name="Kabir Singh", table=8, bio="Startup founder, hiring designers",
         youtube=None,
         blogs=[_blog("kabir", "Zero to One in Pune", ["What our first 10 customers taught us", "Hiring your first designer"], 22)],
         maps=True),
    dict(key="ananya", name="Ananya Das", table=11, bio="Reading, sketching, and too much matcha",
         youtube=None, blogs=None, maps=False),
    dict(key="vikram", name="Vikram Joshi", table=3, bio="Cyclist & map nerd — 1,200 Maps contributions",
         youtube=_yt("vikram", "Pedal Pune", "Cycling routes and gear reviews.", 9800,
                     ["Sinhagad climb under 40 min", "Budget road bike review"]),
         blogs=[_blog("vikram", "Two Wheels Weekly", ["Sahyadri monsoon rides", "Tubeless or not?"], 41)],
         maps=True),
]


def seed_demo_guests(db: Session, cafe_slug: str = "demo") -> None:
    cafe = db.scalar(select(Cafe).where(Cafe.slug == cafe_slug))
    if not cafe:
        return
    for g in GUESTS:
        sub = DEMO_PREFIX + g["key"]
        user = db.scalar(select(User).where(User.google_sub == sub))
        if not user:
            user = User(google_sub=sub, email=f"{g['key']}@example.com", name=g["name"])
            db.add(user)
        user.picture = _avatar(g["key"])
        user.bio = g["bio"]
        user.youtube = g["youtube"]
        user.blogs = g["blogs"]
        user.maps_url = f"https://www.google.com/maps/contrib/demo-{g['key']}" if g["maps"] else ""
        user.share_youtube = user.share_blogs = user.share_maps = True
        db.flush()

        ci = db.scalar(select(CheckIn).where(CheckIn.user_id == user.id, CheckIn.cafe_id == cafe.id))
        if not ci:
            ci = CheckIn(user_id=user.id, cafe_id=cafe.id, table_no=g["table"], checked_in_at=utcnow(), expires_at=utcnow())
            db.add(ci)
        ci.table_no = g["table"]
        ci.visible = True
        ci.expires_at = utcnow() + timedelta(days=30)  # stay "in the room" while developing
    db.commit()


def remove_demo_guests(db: Session) -> None:
    for u in db.scalars(select(User).where(User.google_sub.like(DEMO_PREFIX + "%"))).all():
        db.delete(u)
    db.commit()
