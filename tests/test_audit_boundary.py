"""`apps/audit` es una dependencia hoja con una sola puerta de escritura.

Recorre con `ast` todos los módulos de `backend/` y prueba dos reglas:

- Fuera de `apps/audit`, lo único que se importa de `apps.audit` es
  `record_activity` de `apps.audit.services`; nadie importa `ActivityLog`.
  La excepción es `tests/factories.py`, que expone `activity_count` para que
  los tests de otras apps asserteen la bitácora sin tocar el modelo.
- `apps/audit` no importa ninguna app de dominio; solo la autenticación y
  la permission class de `apps.auth` para su admin view.
"""
import ast
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
AUDIT_DIR = BACKEND_DIR / "apps" / "audit"
SKIPPED_DIRS = {".venv", "__pycache__", "node_modules"}
AUDIT_TEST_SUPPORT = BACKEND_DIR / "tests" / "factories.py"

ALLOWED_AUDIT_IMPORTS = {("apps.audit.services", "record_activity")}
ALLOWED_AUDIT_DEPENDENCIES = ("apps.audit", "apps.auth.authentication", "apps.auth.permissions")


def _python_modules():
    for path in BACKEND_DIR.rglob("*.py"):
        if SKIPPED_DIRS.isdisjoint(path.relative_to(BACKEND_DIR).parts):
            yield path


def _imports(path):
    """Devuelve `(module, name)` por cada import; `name` es None en `import x`."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, None
        elif isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                yield node.module, alias.name


def _is_audit(module):
    return module == "apps.audit" or module.startswith("apps.audit.")


def test_only_record_activity_is_imported_from_audit_outside_the_app():
    offenders = []
    for path in _python_modules():
        if path.is_relative_to(AUDIT_DIR) or path == AUDIT_TEST_SUPPORT:
            continue
        for module, name in _imports(path):
            if name == "ActivityLog" or (
                _is_audit(module) and (module, name) not in ALLOWED_AUDIT_IMPORTS
            ):
                offenders.append(f"{path.relative_to(BACKEND_DIR)}: {module}.{name}")

    assert offenders == []


def test_audit_does_not_import_domain_apps():
    offenders = []
    for path in AUDIT_DIR.rglob("*.py"):
        for module, name in _imports(path):
            if module.startswith("apps.") and not module.startswith(
                ALLOWED_AUDIT_DEPENDENCIES
            ):
                offenders.append(f"{path.relative_to(BACKEND_DIR)}: {module}.{name}")

    assert offenders == []


def test_the_boundary_check_sees_the_real_callers():
    # Si el recorrido no encontrara ningún llamador, las reglas de arriba
    # pasarían sin probar nada.
    callers = {
        path.relative_to(BACKEND_DIR).as_posix()
        for path in _python_modules()
        if ("apps.audit.services", "record_activity") in set(_imports(path))
        and not path.is_relative_to(AUDIT_DIR)
    }

    assert "apps/checkout/webhook_views.py" in callers
    assert "apps/quotes/admin_services.py" in callers
