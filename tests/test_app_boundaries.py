"""El grafo de imports entre apps de `apps/` no tiene ciclos.

Se arma con `ast` sobre todo el código de las apps (también los imports dentro
de funciones), sin `tests/` ni `migrations/`. Las migraciones dependen entre
sí por su propio grafo y los tests pueden cruzar apps libremente.
"""
import ast
from collections import defaultdict
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
APPS_DIR = BACKEND_DIR / "apps"
SKIPPED_DIRS = {"tests", "migrations", "__pycache__"}

# Autenticación, permission class, sesión y throttles de `apps.auth`: todas
# las views los usan para cablearse, como usarían DRF. No cuentan como
# dependencia de dominio; `test_auth_request_infrastructure_is_self_contained`
# garantiza que ignorarlos no esconde un ciclo.
AUTH_REQUEST_INFRASTRUCTURE = {
    "apps.auth.authentication",
    "apps.auth.permissions",
    "apps.auth.sessions",
    "apps.auth.utils.throttling",
}

# Paquetes hoja: cualquier app puede importarlos porque ellos no importan a nadie.
LEAF_PACKAGES = ("common", "numbering")

CUSTOMER_RESOLUTION_NAMES = {
    "customer_for_user",
    "resolve_guest_customer",
    "link_guest_history",
}


def _source_files(root=APPS_DIR):
    for path in root.rglob("*.py"):
        if SKIPPED_DIRS.isdisjoint(path.relative_to(APPS_DIR).parts):
            yield path


def _module_name(path):
    parts = path.relative_to(BACKEND_DIR).with_suffix("").parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


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


def _app_of(module):
    parts = module.split(".")
    return parts[1] if parts[0] == "apps" and len(parts) > 1 else None


def _import_graph():
    graph = defaultdict(set)
    for path in _source_files():
        source_app = path.relative_to(APPS_DIR).parts[0]
        for module, _name in _imports(path):
            target_app = _app_of(module)
            if target_app in (None, source_app) or module in AUTH_REQUEST_INFRASTRUCTURE:
                continue
            graph[source_app].add(target_app)
    return graph


def _find_cycle(graph):
    """Primer ciclo como lista de apps (`[a, b, a]`), o `None`."""
    visiting, done = [], set()

    def visit(app):
        if app in visiting:
            return visiting[visiting.index(app):] + [app]
        if app in done:
            return None
        visiting.append(app)
        for target in sorted(graph.get(app, ())):
            cycle = visit(target)
            if cycle:
                return cycle
        visiting.pop()
        done.add(app)
        return None

    for app in sorted(graph):
        cycle = visit(app)
        if cycle:
            return cycle
    return None


def test_there_are_no_import_cycles_between_apps():
    assert _find_cycle(_import_graph()) is None


def test_the_cycle_detector_finds_a_cycle():
    assert _find_cycle({"a": {"b"}, "b": {"c"}, "c": {"a"}}) == ["a", "b", "c", "a"]
    assert _find_cycle({"a": {"b"}, "b": set()}) is None


def test_auth_request_infrastructure_is_self_contained():
    offenders = [
        f"{_module_name(path)}: {module}"
        for path in _source_files(APPS_DIR / "auth")
        if _module_name(path) in AUTH_REQUEST_INFRASTRUCTURE
        for module, _name in _imports(path)
        if _app_of(module) not in (None, "auth", "common")
    ]

    assert offenders == []


def test_leaf_packages_import_no_other_app():
    offenders = [
        f"{path.relative_to(BACKEND_DIR).as_posix()}: {module}"
        for leaf in LEAF_PACKAGES
        for path in _source_files(APPS_DIR / leaf)
        for module, _name in _imports(path)
        if _app_of(module) not in (None, leaf)
    ]

    assert offenders == []


def test_common_has_no_models_views_or_migrations():
    common = APPS_DIR / "common"

    assert not any((common / name).exists() for name in ("models.py", "models", "migrations"))
    assert not list(common.glob("*views.py"))


def test_customer_resolution_is_only_imported_from_customers():
    offenders = [
        f"{path.relative_to(BACKEND_DIR).as_posix()}: {module}.{name}"
        for path in BACKEND_DIR.rglob("*.py")
        if ".venv" not in path.parts
        for module, name in _imports(path)
        if name in CUSTOMER_RESOLUTION_NAMES and module != "apps.customers.services"
    ]

    assert offenders == []


def test_the_graph_sees_the_real_dependencies():
    # Si el recorrido no encontrara ningún import, las reglas de arriba
    # pasarían sin probar nada.
    graph = _import_graph()

    assert {"customers", "numbering", "common", "tax"} <= graph["checkout"]
    assert {"checkout", "customers"} <= graph["quotes"]
    assert "auth" in graph["customers"]


def test_migrations_only_import_generated_model_callables():
    """Una migración que importa código de la app se rompe con cualquier
    renombre posterior; solo se admiten los callables de modelos que escribe
    `makemigrations` (defaults como `new_user_id`)."""
    offenders = []
    for path in APPS_DIR.glob("*/migrations/*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            elif isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            else:
                continue
            for name in names:
                if name.startswith("apps.") and ".models" not in name:
                    offenders.append(f"{path.relative_to(BACKEND_DIR)}: {name}")
    assert offenders == []
