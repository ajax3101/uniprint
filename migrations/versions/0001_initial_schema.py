"""Initial UniPrint service, inventory, and audit schema.

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-08
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "departments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False, unique=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("department_id", sa.String(36), sa.ForeignKey("departments.id"), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_table(
        "printer_models",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("manufacturer", sa.String(120), nullable=False),
        sa.Column("model_name", sa.String(160), nullable=False),
        sa.UniqueConstraint("manufacturer", "model_name", name="uq_printer_model_name"),
    )
    op.create_table(
        "cartridge_models",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("manufacturer", sa.String(120), nullable=False),
        sa.Column("model_name", sa.String(160), nullable=False),
        sa.Column("article_number", sa.String(100), nullable=True),
        sa.Column("rated_pages", sa.Integer(), nullable=True),
        sa.Column("rated_pages_source", sa.String(500), nullable=True),
        sa.UniqueConstraint("manufacturer", "model_name", name="uq_cartridge_model_name"),
    )
    op.create_table(
        "printer_cartridge_compatibility",
        sa.Column("printer_model_id", sa.String(36), sa.ForeignKey("printer_models.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("cartridge_model_id", sa.String(36), sa.ForeignKey("cartridge_models.id", ondelete="CASCADE"), primary_key=True),
    )
    op.create_table(
        "printers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("asset_number", sa.String(100), nullable=False, unique=True),
        sa.Column("printer_model_id", sa.String(36), sa.ForeignKey("printer_models.id"), nullable=False),
        sa.Column("department_id", sa.String(36), sa.ForeignKey("departments.id"), nullable=True),
        sa.Column("location", sa.String(200), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_table(
        "cartridges",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("asset_code", sa.String(100), nullable=False, unique=True),
        sa.Column("cartridge_model_id", sa.String(36), sa.ForeignKey("cartridge_models.id"), nullable=False),
        sa.Column("serial_number", sa.String(160), nullable=True),
        sa.Column("status", sa.String(40), nullable=False, server_default="in_stock"),
        sa.Column("refill_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "service_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("request_number", sa.String(40), nullable=False, unique=True),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("department_id", sa.String(36), sa.ForeignKey("departments.id"), nullable=True),
        sa.Column("printer_id", sa.String(36), sa.ForeignKey("printers.id"), nullable=False),
        sa.Column("request_type", sa.String(40), nullable=False),
        sa.Column("description", sa.String(2000), nullable=False, server_default=""),
        sa.Column("status", sa.String(40), nullable=False, server_default="submitted"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "request_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("request_id", sa.String(36), sa.ForeignKey("service_requests.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("from_status", sa.String(40), nullable=True),
        sa.Column("to_status", sa.String(40), nullable=False),
        sa.Column("comment", sa.String(1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "cartridge_movements",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("cartridge_id", sa.String(36), sa.ForeignKey("cartridges.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("request_id", sa.String(36), sa.ForeignKey("service_requests.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("movement_type", sa.String(40), nullable=False, server_default="issue"),
        sa.Column("from_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("to_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("from_status", sa.String(40), nullable=True),
        sa.Column("to_status", sa.String(40), nullable=False, server_default="in_stock"),
        sa.Column("counter_reading", sa.Integer(), nullable=True),
        sa.Column("condition", sa.String(500), nullable=True),
        sa.Column("note", sa.String(1000), nullable=True),
        sa.Column("idempotency_key", sa.String(100), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "cartridge_services",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("cartridge_id", sa.String(36), sa.ForeignKey("cartridges.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("request_id", sa.String(36), sa.ForeignKey("service_requests.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("service_type", sa.String(40), nullable=False, server_default="refill"),
        sa.Column("status", sa.String(40), nullable=False, server_default="in_progress"),
        sa.Column("provider", sa.String(200), nullable=True),
        sa.Column("cost", sa.Numeric(12, 2), nullable=True),
        sa.Column("currency", sa.String(3), nullable=True),
        sa.Column("condition_before", sa.String(500), nullable=True),
        sa.Column("condition_after", sa.String(500), nullable=True),
        sa.Column("test_result", sa.String(1000), nullable=True),
        sa.Column("inspection_result", sa.String(40), nullable=True),
        sa.Column("completion_key", sa.String(100), nullable=True, unique=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    indexes = {
        "cartridges": ["asset_code", "status"],
        "service_requests": ["request_number", "created_by", "status"],
        "request_events": ["request_id"],
        "cartridge_movements": ["cartridge_id", "request_id"],
        "cartridge_services": ["cartridge_id"],
    }
    for table, columns in indexes.items():
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column], unique=False)


def downgrade() -> None:
    indexes = {
        "cartridge_movements": ["cartridge_id", "request_id"],
        "cartridge_services": ["cartridge_id"],
        "request_events": ["request_id"],
        "service_requests": ["request_number", "created_by", "status"],
        "cartridges": ["asset_code", "status"],
    }
    for table, columns in indexes.items():
        for column in columns:
            op.drop_index(f"ix_{table}_{column}", table_name=table)
    for table in (
        "cartridge_services",
        "cartridge_movements",
        "request_events",
        "service_requests",
        "cartridges",
        "printers",
        "printer_cartridge_compatibility",
        "cartridge_models",
        "printer_models",
        "users",
        "departments",
    ):
        op.drop_table(table)
