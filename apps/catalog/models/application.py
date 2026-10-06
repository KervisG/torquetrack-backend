from django.db import models

from apps.common.ids import random_id

CODE_MAX_LENGTH = 120


class Application(models.Model):
    """Un rango de años de una marca con un motor (y los modelos que lo montan).

    `code` es el id estable (`ford-73-powerstroke-1994-1997`) que usan el SPA,
    `applicationIds` y la semilla; el `id` numérico lo genera la base y no
    sobrevive a una reimportación, así que nadie fuera de la base lo usa."""

    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=CODE_MAX_LENGTH, unique=True)
    data = models.JSONField(default=dict)

    class Meta:
        db_table = "applications"

    def __str__(self) -> str:
        return self.code or str(self.pk)

    def save(self, *args, **kwargs):
        # Igual que el slug del producto: las aplicaciones nacen por la
        # semilla, el ORM de los tests y migraciones, y todas necesitan el
        # código antes del INSERT.
        if not self.code:
            self.code = str((self.data or {}).get("id") or "").strip()[:CODE_MAX_LENGTH] or (
                random_id("APP").lower()
            )
            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                kwargs["update_fields"] = {*update_fields, "code"}
        super().save(*args, **kwargs)
