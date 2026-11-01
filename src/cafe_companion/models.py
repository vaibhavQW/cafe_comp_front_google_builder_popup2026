from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base, utcnow


class Cafe(Base):
    __tablename__ = "cafes"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    tagline: Mapped[str] = mapped_column(String(240), default="")
    currency: Mapped[str] = mapped_column(String(8), default="INR")
    table_count: Mapped[int] = mapped_column(Integer, default=10)

    menu: Mapped[list["MenuItem"]] = relationship(back_populates="cafe", order_by="MenuItem.sort")


class MenuItem(Base):
    __tablename__ = "menu_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    cafe_id: Mapped[int] = mapped_column(ForeignKey("cafes.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(60))
    price_cents: Mapped[int] = mapped_column(Integer)
    prep_minutes: Mapped[int] = mapped_column(Integer, default=3)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    available: Mapped[bool] = mapped_column(Boolean, default=True)
    sort: Mapped[int] = mapped_column(Integer, default=0)

    cafe: Mapped[Cafe] = relationship(back_populates="menu")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    google_sub: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(254))  # never shown to other users
    name: Mapped[str] = mapped_column(String(160))
    picture: Mapped[str] = mapped_column(Text, default="")
    bio: Mapped[str] = mapped_column(String(280), default="")

    # Snapshots fetched with the user's own OAuth consent at sign-in.
    youtube: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    blogs: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Google has no API for a user's Maps contributions, so the user pastes
    # their public contributor-profile link themselves.
    maps_url: Mapped[str] = mapped_column(Text, default="")

    share_youtube: Mapped[bool] = mapped_column(Boolean, default=True)
    share_blogs: Mapped[bool] = mapped_column(Boolean, default=True)
    share_maps: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class CheckIn(Base):
    __tablename__ = "checkins"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    cafe_id: Mapped[int] = mapped_column(ForeignKey("cafes.id", ondelete="CASCADE"), index=True)
    table_no: Mapped[int] = mapped_column(Integer)
    visible: Mapped[bool] = mapped_column(Boolean, default=True)
    checked_in_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)

    user: Mapped[User] = relationship()


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    cafe_id: Mapped[int] = mapped_column(ForeignKey("cafes.id", ondelete="CASCADE"), index=True)
    table_no: Mapped[int] = mapped_column(Integer)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    token: Mapped[str] = mapped_column(String(48), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(16), default="placed", index=True)
    note: Mapped[str] = mapped_column(String(280), default="")
    total_cents: Mapped[int] = mapped_column(Integer, default=0)
    work_minutes: Mapped[int] = mapped_column(Integer, default=3)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ready_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    items: Mapped[list["OrderItem"]] = relationship(back_populates="order", cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    menu_item_id: Mapped[int | None] = mapped_column(ForeignKey("menu_items.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str] = mapped_column(String(120))
    price_cents: Mapped[int] = mapped_column(Integer)
    qty: Mapped[int] = mapped_column(Integer)

    order: Mapped[Order] = relationship(back_populates="items")
