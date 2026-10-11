"""Carga el catálogo en la base de producción desde la máquina local.

`import_catalog` corre aquí contra la base remota por su URL de conexión, sin
entrar al servidor. El script solo arma la
conexión y llama al comando: la validación (precio > 0, `active` booleano) y la
escritura todo o nada son de `import_catalog`, que se corre primero con
`--dry-run` y después, tras confirmar, de verdad.

La URL sale de `DATABASE_URL` en `.env.remote` (ignorado por git; ver
`.env.remote.example`) o del entorno. Nunca se imprime la contraseña.

Uso (desde la raíz del repo, con el venv activo):

    python scripts/load_products.py <products.json> [--applications <applications.json>]
        [--env-file .env.remote] [--dry-run] [--yes]
"""
from __future__ import annotations

import argparse
import os
import sys
from collections.abc import MutableMapping
from pathlib import Path
from urllib.parse import unquote, urlsplit

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_APPLICATIONS = BASE_DIR / "apps" / "catalog" / "data" / "applications.json"
DEFAULT_ENV_FILE = BASE_DIR / ".env.remote"
POSTGRES_SCHEMES = ("postgres", "postgresql")
DEFAULT_POSTGRES_PORT = "5432"
# `dev.py` no exige broker ni HTTPS; `prod.py` se negaría a arrancar sin las
# variables del servidor, que este proceso local no necesita.
SETTINGS_MODULE = "config.settings.dev"
# Solo para este proceso: `import_catalog` no firma sesiones ni enlaces. Si el
# `.env` local define otra, `setdefault` la respeta.
PLACEHOLDER_SECRET_KEY = "load-products-script-placeholder-not-a-real-secret"


def database_env(url: str) -> dict[str, str]:
    """Traduce la URL de la base remota a las variables `POSTGRES_*` que leen
    los settings. La conexión sale de la red del servidor: `DATABASE_SSL`
    siempre."""
    parts = urlsplit(url.strip())
    if parts.scheme not in POSTGRES_SCHEMES:
        raise ValueError("DATABASE_URL must start with postgresql://")
    name = unquote(parts.path.lstrip("/"))
    if not parts.hostname or not name or not parts.username or parts.password is None:
        raise ValueError("DATABASE_URL must include user, password, host and database name")
    return {
        "POSTGRES_DB": name,
        "POSTGRES_USER": unquote(parts.username),
        "POSTGRES_PASSWORD": unquote(parts.password),
        "POSTGRES_HOST": parts.hostname,
        "POSTGRES_PORT": str(parts.port or DEFAULT_POSTGRES_PORT),
        "DATABASE_SSL": "true",
    }


def read_env_file(path: Path) -> dict[str, str]:
    """`CLAVE=valor` por línea; ignora vacías y comentarios y quita comillas."""
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def _parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Load products and applications into the remote database."
    )
    parser.add_argument("products", type=Path, help="Path to products.json")
    parser.add_argument("--applications", type=Path, default=DEFAULT_APPLICATIONS)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument(
        "--dry-run", action="store_true", help="Validate and print the summary only."
    )
    parser.add_argument("--yes", action="store_true", help="Skip the confirmation prompt.")
    return parser.parse_args(argv)


def main(argv=None, environ: MutableMapping[str, str] | None = None) -> int:
    args = _parse_args(argv)
    environ = os.environ if environ is None else environ

    file_values = read_env_file(args.env_file) if args.env_file.exists() else {}
    url = file_values.get("DATABASE_URL") or environ.get("DATABASE_URL", "")
    if not url:
        print(
            f"DATABASE_URL is not set. Add it to {args.env_file} "
            "(see .env.remote.example) or export it.",
            file=sys.stderr,
        )
        return 2
    try:
        connection = database_env(url)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2

    # Se fija antes de cargar los settings: `base.py` lee el `.env` local con
    # `setdefault`, así que estos valores ganan sobre la base de desarrollo.
    environ.update(connection)
    environ["DJANGO_SETTINGS_MODULE"] = SETTINGS_MODULE
    environ.setdefault("DJANGO_SECRET_KEY", PLACEHOLDER_SECRET_KEY)

    sys.path.insert(0, str(BASE_DIR))
    import django

    django.setup()
    from django.core.management import call_command
    from django.core.management.base import CommandError

    target = (
        f"{connection['POSTGRES_DB']} on "
        f"{connection['POSTGRES_HOST']}:{connection['POSTGRES_PORT']}"
    )
    print(f"Target database: {target}")
    print(f"Products file: {args.products}")
    print(f"Applications file: {args.applications}")
    files = {"products": args.products, "applications": args.applications}
    try:
        call_command("import_catalog", dry_run=True, **files)
    except CommandError as error:
        print(f"Validation failed. Nothing was written.\n{error}", file=sys.stderr)
        return 1
    if args.dry_run:
        return 0

    if not args.yes:
        answer = input(f"Write this catalog to {target}? Type 'yes' to continue: ")
        if answer.strip().lower() != "yes":
            print("Aborted. Nothing was written.")
            return 1
    try:
        call_command("import_catalog", **files)
    except CommandError as error:
        print(f"Import failed. Nothing was written.\n{error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
