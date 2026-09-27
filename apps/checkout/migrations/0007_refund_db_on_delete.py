# Lleva el CASCADE del ORM de `refunds.payment_id` a Postgres; ver
# `checkout/0005_db_on_delete`. Va aparte de `0006_refund` porque Django crea
# la FK con SQL diferido al final de esa migración: un RunSQL en la misma
# todavía no la encuentra.
from django.db import migrations

CONSTRAINT = "refunds_payment_id_075bbbe0_fk_payments_id"


def _recreate(on_delete):
    return (
        f"ALTER TABLE refunds DROP CONSTRAINT {CONSTRAINT},"
        f" ADD CONSTRAINT {CONSTRAINT} FOREIGN KEY (payment_id) REFERENCES payments(id)"
        f"{on_delete} DEFERRABLE INITIALLY DEFERRED"
    )


class Migration(migrations.Migration):

    dependencies = [
        ("checkout", "0006_refund"),
    ]

    operations = [
        migrations.RunSQL(_recreate(" ON DELETE CASCADE"), reverse_sql=_recreate("")),
    ]
