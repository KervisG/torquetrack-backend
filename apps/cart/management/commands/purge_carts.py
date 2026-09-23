"""Existe porque `GET /api/admin/carts/` es de solo lectura: el borrado de
carritos vacíos se corre a mano o desde el cron del host."""
from django.core.management.base import BaseCommand

from apps.cart.services import purge_empty_carts


class Command(BaseCommand):
    help = "Delete carts whose items are missing, not an array or empty."

    def handle(self, *args, **options):
        deleted = purge_empty_carts()
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} empty cart(s)."))
