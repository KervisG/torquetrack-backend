# Crea la tabla del cache compartido (`DatabaseCache`, `django_cache`) donde
# viven los contadores de los throttles de `apps/authentication/utils/throttling.py`.
#
# Se hace en una migración y no como paso manual de deploy porque `migrate`
# ya es obligatorio en cada deploy: así ningún entorno queda sin la tabla y
# los throttles no fallan con "relation does not exist". Reusa
# `createcachetable`, que lee `CACHES` en tiempo de ejecución: crea solo las
# tablas de los caches `DatabaseCache` configurados, no hace nada si
# `CACHE_URL` apunta a Redis y es idempotente si la tabla ya existe.
from django.core.management import call_command
from django.db import migrations


def create_cache_tables(apps, schema_editor):
    call_command(
        "createcachetable",
        database=schema_editor.connection.alias,
        verbosity=0,
    )


class Migration(migrations.Migration):

    dependencies = [
        ("authentication", "0001_initial"),
    ]

    operations = [
        # El reverso no borra la tabla: es un cache, dejarla no rompe nada y
        # borrarla podría llevarse la de otro cache configurado a mano.
        migrations.RunPython(create_cache_tables, migrations.RunPython.noop),
    ]
