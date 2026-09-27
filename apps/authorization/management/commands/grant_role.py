"""Asigna o quita el Role de una cuenta ya registrada.

Reemplaza al viejo alta de admins por terminal: nadie crea cuentas por aquí.
El primer admin se registra en la tienda (o con `createsuperuser` en
desarrollo) y después se le da el Role con
`python manage.py grant_role --email ... --role admin`.
"""
from django.core.management.base import BaseCommand, CommandError

from apps.authorization.services import NO_ROLE, grant_role


class Command(BaseCommand):
    help = (
        "Assign a role to an already registered account (by email). "
        f"Use --role {NO_ROLE} to remove it. Never creates accounts."
    )

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)
        parser.add_argument(
            "--role",
            required=True,
            help=f"Slug of an existing role (for example admin or employee), or {NO_ROLE}.",
        )

    def handle(self, *args, **options):
        result, status = grant_role(options["email"], options["role"])
        if status >= 400:
            raise CommandError(result["error"])

        user, role = result["user"], result["role"]
        if role is None:
            message = f"Removed the role of {user.email}"
        else:
            message = f"Granted {role.slug} to {user.email}"
        self.stdout.write(self.style.SUCCESS(message))
        if not user.active:
            self.stdout.write(self.style.WARNING("The account is inactive."))
