from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class CartridgeModelCreate(BaseModel):
    manufacturer: str = Field(min_length=1, max_length=120)
    model_name: str = Field(min_length=1, max_length=160)
    article_number: str | None = Field(default=None, max_length=100)
    rated_pages: int | None = Field(default=None, ge=1)
    rated_pages_source: str | None = Field(default=None, max_length=500)


class CartridgeModelRead(ORMModel):
    id: str
    manufacturer: str
    model_name: str
    article_number: str | None
    rated_pages: int | None
    rated_pages_source: str | None


class PrinterModelCreate(BaseModel):
    manufacturer: str = Field(min_length=1, max_length=120)
    model_name: str = Field(min_length=1, max_length=160)
    compatible_cartridge_model_ids: list[str] = Field(default_factory=list)


class PrinterModelRead(ORMModel):
    id: str
    manufacturer: str
    model_name: str


class PrinterCreate(BaseModel):
    asset_number: str = Field(min_length=1, max_length=100)
    printer_model_id: str
    department_id: str | None = None
    location: str | None = Field(default=None, max_length=200)


class PrinterRead(ORMModel):
    id: str
    asset_number: str
    printer_model_id: str
    department_id: str | None
    location: str | None
    active: bool


class CartridgeCreate(BaseModel):
    asset_code: str = Field(min_length=1, max_length=100)
    cartridge_model_id: str
    serial_number: str | None = Field(default=None, max_length=160)


class CartridgeRead(ORMModel):
    id: str
    asset_code: str
    cartridge_model_id: str
    cartridge_model: CartridgeModelRead
    serial_number: str | None
    status: str
    refill_count: int
    created_at: datetime


class CartridgeMovementRead(ORMModel):
    id: str
    request_id: str | None
    actor_id: str
    movement_type: str
    from_user_id: str | None
    to_user_id: str | None
    from_status: str | None
    to_status: str
    counter_reading: int | None
    condition: str | None
    note: str | None
    created_at: datetime


class CartridgeInstallationRead(ORMModel):
    id: str
    request_id: str
    installed_by: str
    install_counter: int | None
    condition_at_install: str | None
    installed_at: datetime
    cartridge: CartridgeRead
    printer: PrinterRead


class RequestCreate(BaseModel):
    printer_id: str
    request_type: str = Field(pattern="^(refill|replacement|repair|maintenance|other)$")
    description: str = Field(default="", max_length=2000)


class RequestRead(ORMModel):
    id: str
    request_number: str
    created_by: str
    printer_id: str
    request_type: str
    description: str
    status: str
    created_at: datetime


class RequestTransition(BaseModel):
    target_status: str = Field(pattern="^(in_review|approved|rejected|processing|fulfilled|completed|cancelled)$")
    comment: str | None = Field(default=None, max_length=1000)


class RequestEventRead(ORMModel):
    id: str
    actor_id: str
    event_type: str
    from_status: str | None
    to_status: str
    comment: str | None
    created_at: datetime


class IssueCartridge(BaseModel):
    cartridge_code: str = Field(min_length=1, max_length=100)
    recipient_id: str = Field(min_length=1, max_length=36)


class InstallCartridge(BaseModel):
    cartridge_code: str = Field(min_length=1, max_length=100)
    counter_reading: int | None = Field(default=None, ge=0)
    condition: str | None = Field(default=None, max_length=500)


class RemoveCartridge(BaseModel):
    cartridge_code: str = Field(min_length=1, max_length=100)
    counter_reading: int | None = Field(default=None, ge=0)
    condition: str | None = Field(default=None, max_length=500)
    note: str | None = Field(default=None, max_length=1000)


class ReturnCartridge(BaseModel):
    cartridge_code: str = Field(min_length=1, max_length=100)
    recipient_id: str = Field(min_length=1, max_length=36)
    outcome: str = Field(pattern="^(stock|refill|repair|writeoff)$")
    condition: str | None = Field(default=None, max_length=500)
    counter_reading: int | None = Field(default=None, ge=0)
    note: str | None = Field(default=None, max_length=1000)


class RefillCompletion(BaseModel):
    provider: str | None = Field(default=None, max_length=200)
    cost: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    currency: str | None = Field(default=None, pattern="^[A-Z]{3}$")
    condition_after: str | None = Field(default=None, max_length=500)
    test_result: str = Field(min_length=1, max_length=1000)


class RepairCompletion(RefillCompletion):
    pass


class CartridgeInspection(BaseModel):
    result: str = Field(pattern="^(stock|repair|writeoff)$")
    condition: str | None = Field(default=None, max_length=500)
    note: str | None = Field(default=None, max_length=1000)
