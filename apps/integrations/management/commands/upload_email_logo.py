"""Sube el logo de los correos al bucket de Spaces.

Una bandeja de correo solo puede mostrar una imagen pública: el logo vive en
el CDN y `EMAIL_LOGO_URL` apunta ahí. Se corre una vez, y de nuevo solo si el
logo cambia (con otro `EMAIL_LOGO_KEY`, porque el CDN cachea cada nombre un
año).
"""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.integrations.exceptions import ProviderError
from apps.integrations.storage import spaces

LOGO_FILE = settings.BASE_DIR / "static" / "brand" / "email-logo.png"


class Command(BaseCommand):
    help = "Upload the email logo (static/brand/email-logo.png) to the Spaces bucket."

    def handle(self, *args, **options):
        try:
            url = spaces.upload(
                key=settings.EMAIL_LOGO_KEY,
                content=LOGO_FILE.read_bytes(),
                content_type="image/png",
            )
        except ProviderError as exc:
            raise CommandError(f"Logo not uploaded: {exc}") from exc
        self.stdout.write(f"Email logo uploaded: {url}")
