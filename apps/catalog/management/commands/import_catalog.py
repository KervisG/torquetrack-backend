"""Las aplicaciones se cruzan por `code` (el `id` de la semilla): se actualizan
en su lugar y se borran solo las que la semilla ya no trae, así sus filas de
`product_fitments` sobreviven a una reimportación. El fitment de los productos
de la semilla se rearma desde sus `applicationIds` (o su texto). Los productos
que no están en la semilla (por ejemplo, los creados desde el panel) no se
tocan.

`active` es opcional por producto: la semilla no lo trae (todo queda activo) y
la exportación del panel (`GET /api/admin/products/export/`) sí, para que un
producto desactivado siga desactivado al cargarlo en otro servidor. Va a la
columna y nunca a `data`.

Las categorías (`categories.json`, nombre y sección de la portada) se cargan
antes que los productos: así un producto no crea su categoría en `OTHER` cuando
el archivo ya dice en qué sección va. Se cruzan por su forma canónica.

`--only-missing` (el que corre el contenedor al arrancar) solo inserta lo que
falta: no actualiza, no borra aplicaciones ni rearma el fitment existente."""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.catalog.models import Application, Category, Product
from apps.catalog.services import (
    backfill_product_fitments,
    ensure_brands,
    ensure_category,
    import_categories,
    invalid_category_rows,
    product_price_error,
)
from apps.catalog.services.search import canonical_category

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


def _validate_categories(categories) -> None:
    errors = invalid_category_rows(categories)
    if errors:
        raise CommandError("Invalid categories:\n" + "\n".join(f"  - {e}" for e in errors))


def _ensure_brands_and_category(data: dict) -> None:
    """Un producto importado deja creadas sus marcas y su categoría, igual que
    uno guardado desde el panel."""
    ensure_brands(data.get("manufacturer"))
    ensure_category(data.get("category"))


class Command(BaseCommand):
    help = "Import the seed catalog (products and applications) into the database."

    def add_arguments(self, parser):
        parser.add_argument("--products", type=Path, default=DATA_DIR / "products.json")
        parser.add_argument(
            "--applications", type=Path, default=DATA_DIR / "applications.json"
        )
        parser.add_argument("--categories", type=Path, default=DATA_DIR / "categories.json")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Validate the files and print the summary without writing.",
        )
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument(
            "--if-empty",
            action="store_true",
            help="Import only when there are no products yet.",
        )
        mode.add_argument(
            "--only-missing",
            action="store_true",
            help=(
                "Insert only the products and applications that do not exist yet "
                "(used on container start)."
            ),
        )

    def handle(self, *args, **options):
        if options["if_empty"] and Product.objects.exists():
            self.stdout.write("Catalog already loaded: import skipped.")
            return

        products = _read_json(options["products"])
        applications = _read_json(options["applications"])
        categories = _read_json(options["categories"])
        _validate_categories(categories)
        if options["only_missing"]:
            self._import_missing(
                products, applications, categories, dry_run=options["dry_run"]
            )
            return

        _validate(products)
        inactive = sum(1 for product in products if product.get("active") is False)
        self.stdout.write(
            f"Products to import: {len(products)} "
            f"({len(products) - inactive} active, {inactive} inactive)"
        )
        self.stdout.write(f"Applications to import: {len(applications)}")
        self.stdout.write(f"Categories to import: {len(categories)}")
        if options["dry_run"]:
            self.stdout.write("Dry run: nothing was written.")
            return

        # Todo o nada: una semilla a medias deja fitment apuntando a productos
        # que no existen.
        with transaction.atomic():
            import_categories(categories, only_missing=False)
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
                _ensure_brands_and_category(data)

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
        self.stdout.write(f"Categories imported: {len(categories)}")
        self.stdout.write(f"Fitment rows created: {fitment['links']}")

    def _import_missing(self, products, applications, categories, *, dry_run):
        """El contenedor lo corre en cada arranque: agrega solo lo que falta y
        nunca actualiza ni borra, para no pisar lo editado o desactivado desde
        el panel. Así un archivo que crece entra solo en el siguiente deploy."""
        existing_products = set(Product.objects.values_list("id", flat=True))
        existing_codes = set(Application.objects.values_list("code", flat=True))
        new_products = [p for p in products if str(p["id"]) not in existing_products]
        new_applications = [a for a in applications if str(a["id"]) not in existing_codes]
        existing_categories = set(Category.objects.values_list("value", flat=True))
        new_categories = [
            c for c in categories if canonical_category(c["name"]) not in existing_categories
        ]

        _validate(new_products)
        self.stdout.write(
            f"Missing products: {len(new_products)} "
            f"(skipped {len(products) - len(new_products)} existing)"
        )
        self.stdout.write(f"Missing applications: {len(new_applications)}")
        self.stdout.write(f"Missing categories: {len(new_categories)}")
        if dry_run:
            self.stdout.write("Dry run: nothing was written.")
            return
        if not new_products and not new_applications and not new_categories:
            self.stdout.write("Catalog up to date: nothing to import.")
            return

        # Las aplicaciones van primero: el fitment de los productos nuevos las
        # referencia por código. Las categorías existentes no se tocan: su
        # sección es la que eligió el panel.
        with transaction.atomic():
            import_categories(new_categories, only_missing=True)
            now = timezone.now()
            Application.objects.bulk_create(
                Application(code=str(item["id"]), data=item) for item in new_applications
            )
            for product in new_products:
                data = {key: value for key, value in product.items() if key != "active"}
                Product.objects.create(
                    id=str(product["id"]),
                    data=data,
                    active=product.get("active", True),
                    updated_at=now,
                )
                _ensure_brands_and_category(data)
            fitment = backfill_product_fitments(
                Product.objects.filter(id__in=[str(p["id"]) for p in new_products]),
                replace=True,
            )

        self.stdout.write(f"Products imported: {len(new_products)}")
        self.stdout.write(f"Applications imported: {len(new_applications)}")
        self.stdout.write(f"Categories imported: {len(new_categories)}")
        self.stdout.write(f"Fitment rows created: {fitment['links']}")
