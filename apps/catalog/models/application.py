from django.db import models


class Application(models.Model):
    id = models.BigAutoField(primary_key=True)
    data = models.JSONField(default=dict)

    class Meta:
        db_table = "applications"

    def __str__(self) -> str:
        return str(self.pk)
