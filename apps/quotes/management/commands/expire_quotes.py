"""Existe porque `GET /api/admin/quotes/` es de solo lectura: el vencimiento
se muestra al leer y este comando lo persiste, a mano o desde el cron del host."""
from django.core.management.base import BaseCommand

from apps.quotes.services import expire_stale_quotes


class Command(BaseCommand):
    help = "Mark open quotes past their expiry date as EXPIRED."

    def handle(self, *args, **options):
        expired = expire_stale_quotes()
        self.stdout.write(self.style.SUCCESS(f"Expired {expired} quote(s)."))
