"""Single source of truth for ERP module keys, default packages, and module
dependencies. Shared by backend feature-gating (actor.py::require_feature) and meant
to be mirrored by the frontend nav (moduleKey tags), same pattern as Tolkyn's
app/core/features.py.
"""

MODULES: dict[str, str] = {
    "crm": "Customer Relationship Management",
    "inventory": "Inventory & Stock Valuation",
    "sales": "Sales & Invoicing",
    "purchasing": "Purchasing",
    "accounting": "Accounting & General Ledger",
    "pos": "Point of Sale",
    "hr": "HR & Payroll",
    "assets": "Fixed Assets",
    "manufacturing": "Manufacturing",
}

# A module in this map cannot be enabled unless its dependencies are also enabled.
# accounting is pulled in automatically by sales/purchasing: you can't invoice or
# receive goods without a GL to post to.
MODULE_DEPENDENCIES: dict[str, list[str]] = {
    "sales": ["accounting", "inventory"],
    "purchasing": ["accounting", "inventory"],
    "pos": ["accounting", "inventory", "sales"],
    "manufacturing": ["inventory", "accounting"],
    "hr": ["accounting"],  # payroll posts salary accruals to the GL
    "assets": ["accounting"],
}

DEFAULT_PACKAGES: dict[str, dict] = {
    "starter": {
        "name": "Starter",
        "modules": ["crm", "inventory", "sales", "accounting", "pos"],
        "limits": {"max_users": 5, "max_sku": 500},
        "is_default": True,
    },
    "growth": {
        "name": "Growth",
        "modules": ["crm", "inventory", "sales", "purchasing", "accounting", "pos", "hr", "assets"],
        "limits": {"max_users": 25, "max_sku": 5000},
        "is_default": False,
    },
    "enterprise": {
        "name": "Enterprise",
        "modules": ["*"],
        "limits": {"max_users": None, "max_sku": None},
        "is_default": False,
    },
}


def dependents_of(module: str) -> set[str]:
    """Every module that (transitively) needs `module` — switching `module` off
    must switch these off too, or they'd be enabled with a missing foundation."""
    result: set[str] = set()
    changed = True
    while changed:
        changed = False
        for candidate, deps in MODULE_DEPENDENCIES.items():
            if candidate not in result and (module in deps or result & set(deps)):
                result.add(candidate)
                changed = True
    return result


def effective_workspace_modules(
    package_modules: list[str],
    workspace_overrides: dict[str, bool] | None,
    user_overrides: dict[str, bool] | None = None,
) -> set[str]:
    """The single place a member's module set is decided:

    1. the workspace's Package,
    2. + the platform super-admin's per-workspace switches (Workspace.module_overrides),
    3. + per-user overrides (User.module_overrides),
    4. + dependencies (enabling sales pulls in accounting and inventory),
    5. then every module the super admin switched OFF for this workspace — and
       everything that depends on it — is removed. A per-user grant can never
       re-enable a module the customer has had turned off.
    """
    modules = resolve_effective_modules(package_modules, workspace_overrides)
    modules = resolve_effective_modules(sorted(modules), user_overrides)
    modules = expand_with_dependencies(modules)
    for key, enabled in (workspace_overrides or {}).items():
        if not enabled:
            modules.discard(key)
            modules -= dependents_of(key)
    return modules


def resolve_effective_modules(
    package_modules: list[str], overrides: dict[str, bool] | None = None
) -> set[str]:
    """package_modules: Package.modules (["*"] means every key in MODULES).
    overrides: User.module_overrides, e.g. {"purchasing": True, "crm": False} —
    force-grants/force-removes on top of the package.
    """
    if "*" in package_modules:
        effective = set(MODULES.keys())
    else:
        effective = set(package_modules)

    for key, granted in (overrides or {}).items():
        if granted:
            effective.add(key)
        else:
            effective.discard(key)

    return effective


def expand_with_dependencies(modules: set[str]) -> set[str]:
    """Given a set of enabled module keys, pull in every transitive dependency
    (e.g. enabling 'sales' also enables 'accounting' and 'inventory')."""
    expanded = set(modules)
    changed = True
    while changed:
        changed = False
        for module in list(expanded):
            for dep in MODULE_DEPENDENCIES.get(module, []):
                if dep not in expanded:
                    expanded.add(dep)
                    changed = True
    return expanded
