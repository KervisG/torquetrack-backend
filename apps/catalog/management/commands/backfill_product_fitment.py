"""Crea las filas de `ProductFitment` desde el texto de cada producto
(`backfill_product_fitments`). Idempotente: los productos que ya tienen filas
no se tocan. Lo que no se pudo leer se lista para cargarlo a mano en el panel."""

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.catalog.models import Product
from apps.catalog.services import backfill_product_fitments


class _DryRunRollback(Exception):
    pass


def _ids(values) -> str:
    return f"{len(values)} ({', '.join(values)})" if values else "0"


class Command(BaseCommand):
    help = "Backfill product-to-application fitment rows from product compatibility text."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true", help="Report what would be linked without saving."
        )

    def handle(self, *args, **options):
        report = {}
        try:
            with transaction.atomic():
                report = backfill_product_fitments(Product.objects.all())
                if options["dry_run"]:
                    raise _DryRunRollback
        except _DryRunRollback:
            pass

        unknown = report["unknownApplicationIds"]
        lines = [
            f"Products scanned: {report['scanned']}",
            f"Linked from applicationIds: {report['linkedFromIds']}",
            f"Linked from text: {report['linkedFromText']}",
            f"Fitment rows created: {report['links']}",
            f"Skipped (already linked): {report['skippedExisting']}",
            f"Without compatibility data: {report['noData']}",
            f"Unparseable: {_ids(report['unparseable'])}",
            f"No matching application: {_ids(report['unmatched'])}",
            f"Only unknown applicationIds: {_ids(report['unresolved'])}",
            "Unknown applicationIds: "
            + (
                "; ".join(f"{pid}: {', '.join(codes)}" for pid, codes in unknown.items())
                if unknown
                else "0"
            ),
        ]
        if options["dry_run"]:
            lines.append("Dry run: no changes were saved.")
        self.stdout.write("\n".join(lines))
