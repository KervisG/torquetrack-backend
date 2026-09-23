# Retira la tabla `sessions` del Next.js abandonado.
#
# La sesión es la de Django (`django_session`, cookie `SESSION_COOKIE_NAME`) y ningún
# módulo del backend lee `sessions`. Solo existe en bases de desarrollo
# creadas con el viejo `scripts/schema.sql`; en una base nueva es un no-op.
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("tt_auth", "0007_managed_user"),
    ]

    operations = [
        migrations.RunSQL(
            "DROP TABLE IF EXISTS sessions CASCADE",
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
