"""`apps/integrations` es la única puerta hacia los proveedores externos.

Recorre con `ast` todos los módulos de `backend/` y prueba tres reglas:

- Fuera de `apps/integrations`, nadie importa `requests`, `stripe` ni el SDK
  de otro proveedor. Toda llamada saliente pasa por un adaptador.
- Las apps de dominio no se prestan helpers de proveedor entre sí: nadie
  importa `send_email` de `apps.quotes` (sale del adaptador de Resend) ni el
  cálculo de impuestos de `apps.checkout` (es de `apps.tax.services`).
- `apps/integrations` no importa apps de dominio: un adaptador no conoce
  modelos ni reglas de negocio, así cualquier app puede usarlo sin ciclos.
"""
import ast
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
INTEGRATIONS_DIR = BACKEND_DIR / "apps" / "integrations"
SKIPPED_DIRS = {".venv", "__pycache__", "node_modules"}

PROVIDER_PACKAGES = {"requests", "stripe", "easypost", "resend", "taxjar"}
TAX_CALCULATION_NAMES = {"calculate_sales_tax", "FALLBACK_TAX_RATES"}


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


def _outside_integrations():
    for path in _python_modules():
        if not path.is_relative_to(INTEGRATIONS_DIR):
            yield path


def _offender(path, module, name):
    return f"{path.relative_to(BACKEND_DIR).as_posix()}: {module}.{name}"


def test_only_integrations_imports_provider_clients():
    offenders = [
        _offender(path, module, name)
        for path in _outside_integrations()
        for module, name in _imports(path)
        if module.split(".")[0] in PROVIDER_PACKAGES
    ]

    assert offenders == []


def test_send_email_only_comes_from_the_resend_adapter():
    offenders = [
        _offender(path, module, name)
        for path in _outside_integrations()
        for module, name in _imports(path)
        if name == "send_email"
    ]

    assert offenders == []


def test_tax_calculation_only_comes_from_apps_tax():
    offenders = [
        _offender(path, module, name)
        for path in _python_modules()
        for module, name in _imports(path)
        if name in TAX_CALCULATION_NAMES and module != "apps.tax.services"
    ]

    assert offenders == []


def test_integrations_does_not_import_domain_apps():
    offenders = [
        _offender(path, module, name)
        for path in INTEGRATIONS_DIR.rglob("*.py")
        if SKIPPED_DIRS.isdisjoint(path.parts)
        for module, name in _imports(path)
        if (module.startswith("apps.") and not module.startswith("apps.integrations"))
        or module.startswith("tests")
    ]

    assert offenders == []


def test_the_boundary_check_sees_the_real_callers():
    # Si el recorrido no encontrara ningún llamador, las reglas de arriba
    # pasarían sin probar nada.
    def callers(module, name):
        return {
            path.relative_to(BACKEND_DIR).as_posix()
            for path in _outside_integrations()
            if (module, name) in set(_imports(path))
        }

    assert "apps/auth/services.py" in callers("apps.integrations.email", "resend")
    assert "apps/checkout/views.py" in callers("apps.tax.services", "calculate_sales_tax")
    assert "apps/vin/services.py" in callers("apps.integrations.vehicles", "nhtsa")
    adapters = {
        path.relative_to(BACKEND_DIR).as_posix()
        for path in INTEGRATIONS_DIR.rglob("*.py")
        if any(module.split(".")[0] in PROVIDER_PACKAGES for module, _ in _imports(path))
    }
    assert "apps/integrations/payments/stripe.py" in adapters
    assert "apps/integrations/email/resend.py" in adapters
