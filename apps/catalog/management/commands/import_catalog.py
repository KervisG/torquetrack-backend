"""Carga el catálogo semilla (`products` y `applications`) desde
`apps/catalog/data/`.

Es idempotente: cada producto se inserta o se sobrescribe por `id` y queda
activo, y la tabla `applications` se reemplaza completa porque su clave
primaria la genera la base y no hay un identificador estable para cruzarla.
Los productos que no están en la semilla (por ejemplo los creados desde el
panel) no se tocan.
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.catalog.models import Application, Product

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

        # Todo o nada: una semilla a medias deja fitment apuntando a productos
        # que no existen.
        with transaction.atomic():
            now = timezone.now()
            for product in products:
                Product.objects.update_or_create(
                    id=str(product["id"]),
                    defaults={"data": product, "active": True, "updated_at": now},
                )

            Application.objects.all().delete()
            Application.objects.bulk_create(Application(data=item) for item in applications)

        self.stdout.write(f"Products imported: {len(products)}")
        self.stdout.write(f"Applications imported: {len(applications)}")
