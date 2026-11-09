"""Add opaque QR label tokens to physical cartridges.

Revision ID: 0003_label_tokens
Revises: 0002_installations
Create Date: 2026-11-08
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0003_label_tokens"
down_revision: str | None = "0002_installations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("cartridges", sa.Column("label_token", sa.String(36), nullable=True))
    # Existing primary keys are generated as random UUIDs, so they safely backfill
    # an opaque token without exposing a person's or department's identifier.
    op.execute("UPDATE cartridges SET label_token = id WHERE label_token IS NULL")
    cartridges_after_add = sa.Table(
        "cartridges",
        sa.MetaData(),
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("asset_code", sa.String(100), nullable=False),
        sa.Column("cartridge_model_id", sa.String(36), nullable=False),
        sa.Column("serial_number", sa.String(160), nullable=True),
        sa.Column("status", sa.String(40), nullable=False, server_default="in_stock"),
        sa.Column("refill_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("label_token", sa.String(36), nullable=True),
        sa.ForeignKeyConstraint(["cartridge_model_id"], ["cartridge_models.id"]),
        sa.UniqueConstraint("asset_code"),
        sa.Index("ix_cartridges_asset_code", "asset_code"),
        sa.Index("ix_cartridges_status", "status"),
    )
    with op.batch_alter_table("cartridges", copy_from=cartridges_after_add) as batch_op:
        batch_op.alter_column("label_token", existing_type=sa.String(36), nullable=False)
        batch_op.create_unique_constraint("uq_cartridge_label_token", ["label_token"])


def downgrade() -> None:
    with op.batch_alter_table("cartridges") as batch_op:
        batch_op.drop_constraint("uq_cartridge_label_token", type_="unique")
        batch_op.drop_column("label_token")
