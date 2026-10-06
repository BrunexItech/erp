"""restricted application role so row-level security is actually enforced

Revision ID: a1b2c3d4e5f6
Revises: 924860b8d4ca
Create Date: 2026-10-06

RLS policies are skipped for superusers and for table owners that aren't
FORCEd — and the role the app logs in with is normally both. The app now runs
each transaction as `erp_app` (see core/db.py), a role that owns nothing and
has no BYPASSRLS, so the tenant_isolation policies bind.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "924860b8d4ca"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ROLE = "erp_app"


def upgrade() -> None:
    # Roles are cluster-wide, so this may already exist from another database.
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE}') THEN
                CREATE ROLE {ROLE} NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
            END IF;
        END $$;
        """
    )
    # The login role must be allowed to switch to it (a no-op for superusers).
    op.execute(f"GRANT {ROLE} TO CURRENT_USER")
    op.execute(f"GRANT USAGE ON SCHEMA public TO {ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {ROLE}")
    op.execute(f"GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO {ROLE}")
    # ...and on every table a future migration creates.
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {ROLE}")
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO {ROLE}")
    # Migration bookkeeping is not the app's business.
    op.execute(f"REVOKE ALL ON TABLE alembic_version FROM {ROLE}")


def downgrade() -> None:
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM {ROLE}")
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM {ROLE}")
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {ROLE}")
    op.execute(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {ROLE}")
