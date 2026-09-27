# Tablas `users` (el `AUTH_USER_MODEL`) y `account_tokens`. Se rehízo desde
# cero al partir la antigua app de cuentas en `authorization` y `authentication`: exige
# una base nueva (ver `backend/README.md`).
#
# `admin.0001_initial` depende de `AUTH_USER_MODEL` por
# `swappable_dependency`, así que corre después de esta migración y
# `django_admin_log.user_id` nace apuntando a `users`; no hace falta
# `run_before`.
import django.db.models.deletion
import django.db.models.functions.datetime
import django.utils.timezone
from django.db import migrations, models

import apps.authentication.models.user


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("authorization", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="User",
            fields=[
                ("password", models.CharField(max_length=128, verbose_name="password")),
                (
                    "last_login",
                    models.DateTimeField(blank=True, null=True, verbose_name="last login"),
                ),
                (
                    "id",
                    models.TextField(
                        default=apps.authentication.models.user.new_user_id,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("email", models.TextField(unique=True)),
                ("active", models.BooleanField(default=True)),
                ("first_name", models.TextField(blank=True, null=True)),
                ("last_name", models.TextField(blank=True, null=True)),
                ("display_name", models.TextField(blank=True, null=True)),
                ("email_verified_at", models.DateTimeField(blank=True, null=True)),
                (
                    "created_at",
                    models.DateTimeField(
                        db_default=django.db.models.functions.datetime.Now(),
                        default=django.utils.timezone.now,
                    ),
                ),
                (
                    "role",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="users",
                        to="authorization.role",
                    ),
                ),
            ],
            options={
                "db_table": "users",
                "default_permissions": (),
            },
        ),
        migrations.CreateModel(
            name="AccountToken",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                (
                    "purpose",
                    models.TextField(
                        choices=[
                            ("password_reset", "Password reset"),
                            ("email_verification", "Email verification"),
                            ("activation", "Portal activation"),
                        ]
                    ),
                ),
                ("token_hash", models.TextField(unique=True)),
                ("email", models.TextField()),
                ("expires_at", models.DateTimeField()),
                ("used_at", models.DateTimeField(blank=True, null=True)),
                (
                    "created_at",
                    models.DateTimeField(
                        db_default=django.db.models.functions.datetime.Now(),
                        default=django.utils.timezone.now,
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="account_tokens",
                        to="authentication.user",
                    ),
                ),
            ],
            options={
                "db_table": "account_tokens",
                "default_permissions": (),
                "indexes": [
                    models.Index(fields=["user", "purpose"], name="account_tokens_user_purpose")
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(
                            ("user__isnull", False), ("purpose", "activation"), _connector="OR"
                        ),
                        name="account_tokens_user_required",
                    )
                ],
            },
        ),
    ]
