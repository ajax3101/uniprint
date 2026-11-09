"""Track physical cartridge installation and removal.

Revision ID: 0002_installations
Revises: 0001_initial
Create Date: 2026-11-08
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0002_installations"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cartridge_installations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("cartridge_id", sa.String(36), sa.ForeignKey("cartridges.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("printer_id", sa.String(36), sa.ForeignKey("printers.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("request_id", sa.String(36), sa.ForeignKey("service_requests.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("installed_by", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("removed_by", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("install_counter", sa.Integer(), nullable=True),
        sa.Column("remove_counter", sa.Integer(), nullable=True),
        sa.Column("condition_at_install", sa.String(500), nullable=True),
        sa.Column("condition_at_removal", sa.String(500), nullable=True),
        sa.Column("installed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_cartridge_installations_cartridge_id", "cartridge_installations", ["cartridge_id"])
    op.create_index("ix_cartridge_installations_printer_id", "cartridge_installations", ["printer_id"])
    op.create_index("ix_cartridge_installations_request_id", "cartridge_installations", ["request_id"])
    op.create_index(
        "uq_cartridge_installation_active",
        "cartridge_installations",
        ["cartridge_id"],
        unique=True,
        sqlite_where=sa.text("removed_at IS NULL"),
        postgresql_where=sa.text("removed_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_cartridge_installation_active", table_name="cartridge_installations")
    op.drop_index("ix_cartridge_installations_request_id", table_name="cartridge_installations")
    op.drop_index("ix_cartridge_installations_printer_id", table_name="cartridge_installations")
    op.drop_index("ix_cartridge_installations_cartridge_id", table_name="cartridge_installations")
    op.drop_table("cartridge_installations")
