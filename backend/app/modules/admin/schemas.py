from datetime import datetime

from pydantic import BaseModel


class ModuleInfo(BaseModel):
    key: str
    name: str
    depends_on: list[str]


class PackageOut(BaseModel):
    id: str
    key: str
    name: str
    modules: list[str]

    class Config:
        from_attributes = True


class WorkspaceAdminOut(BaseModel):
    id: str
    name: str
    is_active: bool
    created_at: datetime
    package_id: str
    package_name: str
    package_modules: list[str]
    module_overrides: dict[str, bool]
    effective_modules: list[str]
    owner_email: str | None
    member_count: int


class WorkspaceAdminUpdate(BaseModel):
    """module_overrides: {"hr": false} switches HR off for this customer,
    {"manufacturing": true} switches on something their package lacks, and
    {"hr": null} clears the override so the package decides again."""

    package_id: str | None = None
    module_overrides: dict[str, bool | None] | None = None
    is_active: bool | None = None
