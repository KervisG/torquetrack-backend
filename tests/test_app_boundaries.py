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

# La permission class de `apps.authorization` y los throttles de
# `apps.authentication`: todas las views los usan para cablearse, como usarían
# DRF. No cuentan como dependencia de dominio;
# `test_request_infrastructure_is_self_contained` garantiza que ignorarlos no
# esconde un ciclo.
REQUEST_INFRASTRUCTURE = {
    "apps.authorization.permissions": "authorization",
    "apps.authentication.utils.throttling": "authentication",
}

# Paquetes hoja: cualquier app puede importarlos porque ellos no importan a nadie.
LEAF_PACKAGES = ("common", "numbering")

CUSTOMER_RESOLUTION_NAMES = {
    "customer_for_user",
    "resolve_guest_customer",
    "link_guest_history",
}
# Paquete dueño de la resolución: `services/__init__.py` la reexporta desde su
# módulo, así que también cuentan sus submódulos.
CUSTOMER_SERVICES = "apps.customers.services"


def _source_files(root=APPS_DIR):
    for path in root.rglob("*.py"):
        if SKIPPED_DIRS.isdisjoint(path.relative_to(APPS_DIR).parts):
            yield path


def _is_request_infrastructure(module):
    """El módulo es uno de `REQUEST_INFRASTRUCTURE` o un submódulo de su paquete."""
    return any(module == name or module.startswith(f"{name}.") for name in REQUEST_INFRASTRUCTURE)


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
            if target_app in (None, source_app) or _is_request_infrastructure(module):
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


def test_request_infrastructure_is_self_contained():
    offenders = [
        f"{_module_name(path)}: {module}"
        for owner in set(REQUEST_INFRASTRUCTURE.values())
        for path in _source_files(APPS_DIR / owner)
        if _is_request_infrastructure(_module_name(path))
        for module, _name in _imports(path)
        if _app_of(module) not in (None, owner, "common")
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
        if name in CUSTOMER_RESOLUTION_NAMES
        and not (module == CUSTOMER_SERVICES or module.startswith(f"{CUSTOMER_SERVICES}."))
    ]

    assert offenders == []


def test_the_graph_sees_the_real_dependencies():
    # Si el recorrido no encontrara ningún import, las reglas de arriba
    # pasarían sin probar nada.
    graph = _import_graph()

    assert {"customers", "numbering", "common", "tax"} <= graph["checkout"]
    assert {"checkout", "customers"} <= graph["quotes"]
    assert "authentication" in graph["customers"]
    assert "authorization" in graph["authentication"]
    assert "audit" in graph["authorization"]


def test_authorization_never_imports_authentication():
    # `authorization` (roles, permisos y gestión de usuarios del panel) está
    # debajo: `authentication.User.role` apunta a su `Role` y el login lee su
    # catálogo. Llega al `User` con `get_user_model()` y la relación inversa
    # `role.users`. Se revisa cada import, también los de la infraestructura
    # de request que el grafo ignora.
    offenders = [
        f"{path.relative_to(BACKEND_DIR).as_posix()}: {module}"
        for path in _source_files(APPS_DIR / "authorization")
        for module, _name in _imports(path)
        if _app_of(module) == "authentication"
    ]

    assert offenders == []


def test_authentication_depends_on_authorization_only_one_way():
    graph = _import_graph()

    assert "authorization" in graph["authentication"]
    assert "authentication" not in graph["authorization"]


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
