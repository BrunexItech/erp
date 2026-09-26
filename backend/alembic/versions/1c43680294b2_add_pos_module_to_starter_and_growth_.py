"""add pos module to starter and growth packages

Revision ID: 1c43680294b2
Revises: 9b2b1fb1f4bb
Create Date: 2026-09-16 11:41:26.037121

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1c43680294b2'
down_revision: Union[str, None] = '9b2b1fb1f4bb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # POS shipped after starter/growth packages were already seeded by the
    # initial migration's bulk_insert (a one-time seed, not re-read from
    # features.py on every signup) — existing workspaces on those packages need
    # their stored `modules` JSON updated directly to pick it up.
    op.execute(
        """
        UPDATE packages
        SET modules = (modules::jsonb || '["pos"]'::jsonb)::json
        WHERE key IN ('starter', 'growth')
          AND NOT (modules::jsonb ? 'pos')
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE packages
        SET modules = (modules::jsonb - 'pos')::json
        WHERE key IN ('starter', 'growth')
        """
    )
