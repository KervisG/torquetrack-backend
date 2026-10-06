"""Las aplicaciones se cruzan por `code` (el `id` de la semilla): se actualizan
en su lugar y se borran solo las que la semilla ya no trae, así sus filas de
`product_fitments` sobreviven a una reimportación. El fitment de los productos
de la semilla se rearma desde sus `applicationIds` (o su texto). Los productos
que no están en la semilla (por ejemplo, los creados desde el panel) no se
tocan."""

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


class Command(BaseCommand):
    help = "Import the seed catalog (products and applications) into the database."

    def add_arguments(self, parser):
        parser.add_argument("--products", type=Path, default=DATA_DIR / "products.json")
        parser.add_argument(
            "--applications", type=Path, default=DATA_DIR / "applications.json"
        )

    def handle(self, *args, **options):
        products = _read_json(options["products"])
        applications = _read_json(options["applications"])

        unpriced = [str(product["id"]) for product in products if product_price_error(product)]
        if unpriced:
            raise CommandError(f"Products without a valid price: {', '.join(unpriced)}")

        # Todo o nada: una semilla a medias deja fitment apuntando a productos
        # que no existen.
        with transaction.atomic():
            now = timezone.now()
            for product in products:
                Product.objects.update_or_create(
                    id=str(product["id"]),
                    defaults={"data": product, "active": True, "updated_at": now},
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
