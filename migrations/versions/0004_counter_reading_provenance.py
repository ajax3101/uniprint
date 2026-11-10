"""Record the source and system-recorded time of counter readings.

Revision ID: 0004_counter_reading_provenance
Revises: 0003_label_tokens
Create Date: 2026-11-09
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0004_counter_reading_provenance"
down_revision: str | None = "0003_label_tokens"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("cartridge_movements", sa.Column("counter_reading_source", sa.String(40), nullable=True))
    op.add_column(
        "cartridge_movements",
        sa.Column("counter_reading_recorded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("cartridge_installations", sa.Column("install_counter_source", sa.String(40), nullable=True))
    op.add_column(
        "cartridge_installations",
        sa.Column("install_counter_recorded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("cartridge_installations", sa.Column("remove_counter_source", sa.String(40), nullable=True))
    op.add_column(
        "cartridge_installations",
        sa.Column("remove_counter_recorded_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Historical measurements came from operator-entered fields. Backfill their
    # source and use the operation timestamp as the time they were recorded.
    op.execute(
        "UPDATE cartridge_movements "
        "SET counter_reading_source = 'manual', counter_reading_recorded_at = created_at "
        "WHERE counter_reading IS NOT NULL"
    )
    op.execute(
        "UPDATE cartridge_installations "
        "SET install_counter_source = 'manual', install_counter_recorded_at = installed_at "
        "WHERE install_counter IS NOT NULL"
    )
    op.execute(
        "UPDATE cartridge_installations "
        "SET remove_counter_source = 'manual', remove_counter_recorded_at = removed_at "
        "WHERE remove_counter IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column("cartridge_installations", "remove_counter_recorded_at")
    op.drop_column("cartridge_installations", "remove_counter_source")
    op.drop_column("cartridge_installations", "install_counter_recorded_at")
    op.drop_column("cartridge_installations", "install_counter_source")
    op.drop_column("cartridge_movements", "counter_reading_recorded_at")
    op.drop_column("cartridge_movements", "counter_reading_source")
