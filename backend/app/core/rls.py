"""Helper called from Alembic migrations right after creating any tenant-owned table.

Usage in a migration:

    from app.core.rls import enable_rls
    op.create_table("products", ..., sa.Column("workspace_id", sa.String(36), nullable=False), ...)
    enable_rls(op, "products")

This is the second line of defense behind TenantRepository (core/db.py): even a service
that bypasses the repository and issues a raw query cannot see or write rows outside the
workspace_id set via `SET LOCAL app.workspace_id` for that transaction.
"""


def enable_rls(operation, table_name: str) -> None:
    operation.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
    operation.execute(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY")
    operation.execute(
        f"""
        CREATE POLICY tenant_isolation ON {table_name}
        USING (workspace_id = current_setting('app.workspace_id', true))
        WITH CHECK (workspace_id = current_setting('app.workspace_id', true))
        """
    )
