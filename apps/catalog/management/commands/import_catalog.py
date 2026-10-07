"""Las aplicaciones se cruzan por `code` (el `id` de la semilla): se actualizan
en su lugar y se borran solo las que la semilla ya no trae, así sus filas de
`product_fitments` sobreviven a una reimportación. El fitment de los productos
de la semilla se rearma desde sus `applicationIds` (o su texto). Los productos
que no están en la semilla (por ejemplo, los creados desde el panel) no se
tocan.

`active` es opcional por producto: la semilla no lo trae (todo queda activo) y
la exportación del panel (`GET /api/admin/products/export/`) sí, para que un
producto desactivado siga desactivado al cargarlo en otro servidor. Va a la
columna y nunca a `data`."""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.catalog.models import Application, Product
from apps.catalog.services import backfill_product_fitments, product_price_error

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def _read_json(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def _id_list(ids: list[str]) -> str:
    return "\n".join(f"  - {product_id}" for product_id in ids)


def _validate(products: list[dict]) -> None:
    """Todo o nada: un error en cualquier producto aborta antes de escribir."""
    unpriced = [str(product["id"]) for product in products if product_price_error(product)]
    if unpriced:
        raise CommandError(
            f"{len(unpriced)} products without a valid price (missing, zero or negative):\n"
            f"{_id_list(unpriced)}"
        )
    bad_active = [
        str(product["id"])
        for product in products
        if "active" in product and not isinstance(product["active"], bool)
    ]
    if bad_active:
        raise CommandError(f"active must be true or false:\n{_id_list(bad_active)}")


class Command(BaseCommand):
    help = "Import the seed catalog (products and applications) into the database."

    def add_arguments(self, parser):
        parser.add_argument("--products", type=Path, default=DATA_DIR / "products.json")
        parser.add_argument(
            "--applications", type=Path, default=DATA_DIR / "applications.json"
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Validate the files and print the summary without writing.",
        )
        parser.add_argument(
            "--if-empty",
            action="store_true",
            help="Import only when there are no products yet (used on container start).",
        )

    def handle(self, *args, **options):
        # El contenedor lo corre en cada arranque: solo carga la primera vez,
        # para no pisar los cambios hechos después desde el panel.
        if options["if_empty"] and Product.objects.exists():
            self.stdout.write("Catalog already loaded: import skipped.")
            return

        products = _read_json(options["products"])
        applications = _read_json(options["applications"])

        _validate(products)
        inactive = sum(1 for product in products if product.get("active") is False)
        self.stdout.write(
            f"Products to import: {len(products)} "
            f"({len(products) - inactive} active, {inactive} inactive)"
        )
        self.stdout.write(f"Applications to import: {len(applications)}")
        if options["dry_run"]:
            self.stdout.write("Dry run: nothing was written.")
            return

        # Todo o nada: una semilla a medias deja fitment apuntando a productos
        # que no existen.
        with transaction.atomic():
            now = timezone.now()
            for product in products:
                data = {key: value for key, value in product.items() if key != "active"}
                Product.objects.update_or_create(
                    id=str(product["id"]),
                    defaults={
                        "data": data,
                        "active": product.get("active", True),
                        "updated_at": now,
                    },
                )

            codes = []
            for item in applications:
                code = str(item["id"])
                codes.append(code)
                Application.objects.update_or_create(code=code, defaults={"data": item})
            Application.objects.exclude(code__in=codes).delete()

            fitment = backfill_product_fitments(
                Product.objects.filter(id__in=[str(product["id"]) for product in products]),
                replace=True,
            )

        self.stdout.write(f"Products imported: {len(products)}")
        self.stdout.write(f"Applications imported: {len(applications)}")
        self.stdout.write(f"Fitment rows created: {fitment['links']}")
