from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, Table, Column, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


printer_cartridge_compatibility = Table(
    "printer_cartridge_compatibility",
    Base.metadata,
    Column("printer_model_id", ForeignKey("printer_models.id", ondelete="CASCADE"), primary_key=True),
    Column("cartridge_model_id", ForeignKey("cartridge_models.id", ondelete="CASCADE"), primary_key=True),
)


class Department(Base):
    __tablename__ = "departments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(200), unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    display_name: Mapped[str] = mapped_column(String(200))
    department_id: Mapped[str | None] = mapped_column(ForeignKey("departments.id"), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class PrinterModel(Base):
    __tablename__ = "printer_models"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    manufacturer: Mapped[str] = mapped_column(String(120))
    model_name: Mapped[str] = mapped_column(String(160))
    cartridge_models: Mapped[list[CartridgeModel]] = relationship(
        secondary=printer_cartridge_compatibility, back_populates="printer_models"
    )
    __table_args__ = (UniqueConstraint("manufacturer", "model_name", name="uq_printer_model_name"),)


class Printer(Base):
    __tablename__ = "printers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    asset_number: Mapped[str] = mapped_column(String(100), unique=True)
    printer_model_id: Mapped[str] = mapped_column(ForeignKey("printer_models.id"))
    department_id: Mapped[str | None] = mapped_column(ForeignKey("departments.id"), nullable=True)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    printer_model: Mapped[PrinterModel] = relationship()


class CartridgeModel(Base):
    __tablename__ = "cartridge_models"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    manufacturer: Mapped[str] = mapped_column(String(120))
    model_name: Mapped[str] = mapped_column(String(160))
    article_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    rated_pages: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rated_pages_source: Mapped[str | None] = mapped_column(String(500), nullable=True)
    printer_models: Mapped[list[PrinterModel]] = relationship(
        secondary=printer_cartridge_compatibility, back_populates="cartridge_models"
    )
    __table_args__ = (UniqueConstraint("manufacturer", "model_name", name="uq_cartridge_model_name"),)


class Cartridge(Base):
    __tablename__ = "cartridges"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    label_token: Mapped[str] = mapped_column(String(36), unique=True, default=lambda: str(uuid4()))
    asset_code: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    cartridge_model_id: Mapped[str] = mapped_column(ForeignKey("cartridge_models.id"))
    serial_number: Mapped[str | None] = mapped_column(String(160), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="in_stock", index=True)
    refill_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    cartridge_model: Mapped[CartridgeModel] = relationship()


class ServiceRequest(Base):
    __tablename__ = "service_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    request_number: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    department_id: Mapped[str | None] = mapped_column(ForeignKey("departments.id"), nullable=True)
    printer_id: Mapped[str] = mapped_column(ForeignKey("printers.id"))
    request_type: Mapped[str] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(String(2000), default="")
    status: Mapped[str] = mapped_column(String(40), default="submitted", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    printer: Mapped[Printer] = relationship()
    events: Mapped[list[RequestEvent]] = relationship(back_populates="request", order_by="RequestEvent.created_at")


class RequestEvent(Base):
    __tablename__ = "request_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    request_id: Mapped[str] = mapped_column(ForeignKey("service_requests.id", ondelete="RESTRICT"), index=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    event_type: Mapped[str] = mapped_column(String(40))
    from_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    to_status: Mapped[str] = mapped_column(String(40))
    comment: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    request: Mapped[ServiceRequest] = relationship(back_populates="events")


class CartridgeMovement(Base):
    __tablename__ = "cartridge_movements"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    cartridge_id: Mapped[str] = mapped_column(ForeignKey("cartridges.id", ondelete="RESTRICT"), index=True)
    request_id: Mapped[str | None] = mapped_column(ForeignKey("service_requests.id", ondelete="RESTRICT"), nullable=True, index=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    movement_type: Mapped[str] = mapped_column(String(40), default="issue")
    from_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    to_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    from_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    to_status: Mapped[str] = mapped_column(String(40), default="in_stock")
    counter_reading: Mapped[int | None] = mapped_column(Integer, nullable=True)
    counter_reading_source: Mapped[str | None] = mapped_column(String(40), nullable=True)
    counter_reading_recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    condition: Mapped[str | None] = mapped_column(String(500), nullable=True)
    note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    cartridge: Mapped[Cartridge] = relationship()


class CartridgeInstallation(Base):
    __tablename__ = "cartridge_installations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    cartridge_id: Mapped[str] = mapped_column(ForeignKey("cartridges.id", ondelete="RESTRICT"), index=True)
    printer_id: Mapped[str] = mapped_column(ForeignKey("printers.id", ondelete="RESTRICT"), index=True)
    request_id: Mapped[str] = mapped_column(ForeignKey("service_requests.id", ondelete="RESTRICT"), index=True)
    installed_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    removed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    install_counter: Mapped[int | None] = mapped_column(Integer, nullable=True)
    install_counter_source: Mapped[str | None] = mapped_column(String(40), nullable=True)
    install_counter_recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    remove_counter: Mapped[int | None] = mapped_column(Integer, nullable=True)
    remove_counter_source: Mapped[str | None] = mapped_column(String(40), nullable=True)
    remove_counter_recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    condition_at_install: Mapped[str | None] = mapped_column(String(500), nullable=True)
    condition_at_removal: Mapped[str | None] = mapped_column(String(500), nullable=True)
    installed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cartridge: Mapped[Cartridge] = relationship()
    printer: Mapped[Printer] = relationship()


Index(
    "uq_cartridge_installation_active",
    CartridgeInstallation.cartridge_id,
    unique=True,
    sqlite_where=text("removed_at IS NULL"),
    postgresql_where=text("removed_at IS NULL"),
)


class CartridgeService(Base):
    __tablename__ = "cartridge_services"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    cartridge_id: Mapped[str] = mapped_column(ForeignKey("cartridges.id", ondelete="RESTRICT"), index=True)
    request_id: Mapped[str | None] = mapped_column(ForeignKey("service_requests.id", ondelete="RESTRICT"), nullable=True)
    service_type: Mapped[str] = mapped_column(String(40), default="refill")
    status: Mapped[str] = mapped_column(String(40), default="in_progress", index=True)
    provider: Mapped[str | None] = mapped_column(String(200), nullable=True)
    cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    condition_before: Mapped[str | None] = mapped_column(String(500), nullable=True)
    condition_after: Mapped[str | None] = mapped_column(String(500), nullable=True)
    test_result: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    inspection_result: Mapped[str | None] = mapped_column(String(40), nullable=True)
    completion_key: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cartridge: Mapped[Cartridge] = relationship()
