"""Crea en la base de producción los productos de marca TorqueTrack desde el
Excel de números TT, desde la máquina local.

Igual que `load_products.py`: arma la conexión con `DATABASE_URL` (de
`.env.remote` o del entorno) y llama a `import_tt_products`, primero con
`--dry-run` y después, tras confirmar, de verdad. La validación y la escritura
todo o nada son del comando.

Uso (desde la raíz del repo, con el venv activo):

    python scripts/load_tt_products.py <archivo.xlsx> [--env-file .env.remote]
        [--dry-run] [--yes]
"""
from __future__ import annotations

import argparse
import os
import sys
from collections.abc import MutableMapping
from pathlib import Path

from load_products import (
    BASE_DIR,
    DEFAULT_ENV_FILE,
    PLACEHOLDER_SECRET_KEY,
    SETTINGS_MODULE,
    database_env,
    read_env_file,
)


def _parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Create the TorqueTrack-brand products in the remote database."
    )
    parser.add_argument("file", type=Path, help="Path to the TT numbers .xlsx")
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
    print(f"Spreadsheet: {args.file}")
    try:
        call_command("import_tt_products", str(args.file), dry_run=True)
    except CommandError as error:
        print(f"Validation failed. Nothing was written.\n{error}", file=sys.stderr)
        return 1
    if args.dry_run:
        return 0

    if not args.yes:
        answer = input(f"Create these products in {target}? Type 'yes' to continue: ")
        if answer.strip().lower() != "yes":
            print("Aborted. Nothing was written.")
            return 1
    try:
        call_command("import_tt_products", str(args.file))
    except CommandError as error:
        print(f"Import failed. Nothing was written.\n{error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
