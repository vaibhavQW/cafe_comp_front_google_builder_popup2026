"""Wait-time estimation: simulate the active order queue across N barista lanes."""

import heapq
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import utcnow
from .models import Order

ACTIVE = ("placed", "preparing")


def order_work_minutes(prep_minutes: list[int]) -> int:
    """Longest item, plus a minute for each additional item (items overlap on the bar)."""
    if not prep_minutes:
        return 1
    return max(prep_minutes) + (len(prep_minutes) - 1)


def simulate(db: Session, cafe_id: int, extra_work: int | None = None) -> tuple[dict[int, datetime], datetime | None]:
    """Return {order_id: estimated ready time} and, if extra_work is given, the ready time
    of a hypothetical new order appended to the queue."""
    now = utcnow()
    orders = db.scalars(
        select(Order).where(Order.cafe_id == cafe_id, Order.status.in_(ACTIVE)).order_by(Order.created_at, Order.id)
    ).all()
    lanes = [now] * max(1, settings.baristas)
    heapq.heapify(lanes)
    etas: dict[int, datetime] = {}

    # Orders already being prepared occupy a lane first.
    for o in sorted(orders, key=lambda o: o.status != "preparing"):
        start = heapq.heappop(lanes)
        if o.status == "preparing" and o.started_at:
            remaining = max(1.0, o.work_minutes - (now - o.started_at).total_seconds() / 60)
        else:
            remaining = o.work_minutes
        done = start + timedelta(minutes=remaining)
        etas[o.id] = done
        heapq.heappush(lanes, done)

    hypothetical = None
    if extra_work is not None:
        hypothetical = heapq.heappop(lanes) + timedelta(minutes=extra_work)
    return etas, hypothetical


def position_in_queue(db: Session, order: Order) -> int:
    ahead = db.scalars(
        select(Order.id).where(
            Order.cafe_id == order.cafe_id,
            Order.status.in_(ACTIVE),
            Order.created_at < order.created_at,
        )
    ).all()
    return len(ahead)
