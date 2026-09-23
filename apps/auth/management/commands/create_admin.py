"""Sin `--password` la contraseña se pide por la terminal para que no quede en
el historial del shell."""
import sys
from getpass import getpass

from django.core.management.base import BaseCommand, CommandError

from apps.auth.admin_services import bootstrap_admin
from apps.auth.models import User
from apps.auth.services import parse_email


class Command(BaseCommand):
    help = "Create or promote a user to the full access admin role (email marked verified)."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)
        parser.add_argument(
            "--password",
            help="Omit it to be prompted. On an existing user, omitting it keeps the password.",
        )

    def handle(self, *args, **options):
        email = parse_email(options["email"])
        if email is None:
            raise CommandError("A valid --email is required.")

        password = options.get("password")
        if password is None and not User.objects.filter(email=email).exists():
            password = self._prompt_password()

        result, status = bootstrap_admin(email, password)
        if status >= 400:
            raise CommandError(result["error"])

        messages = {
            "created": "Created admin",
            "promoted": "Promoted to admin",
            "updated": "Already an admin",
        }
        self.stdout.write(self.style.SUCCESS(f"{messages[result['action']]}: {email}"))

    def _prompt_password(self) -> str:
        if not sys.stdin.isatty():
            raise CommandError("Pass --password or run the command from a terminal.")
        password = getpass("Password: ")
        if password != getpass("Password (again): "):
            raise CommandError("Passwords do not match.")
        if not password:
            raise CommandError("The password cannot be empty.")
        return password
