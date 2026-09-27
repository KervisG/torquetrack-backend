"""Serializers que solo describen `GET /api/admin/activity/`.

El error vive aquí y no en `apps.authorization`: authorization ya llama a
`record_activity`, y importar sus docs cerraría un ciclo entre apps.
"""
from rest_framework import serializers


class ErrorResponseSerializer(serializers.Serializer):
    error = serializers.CharField(help_text="Literal English error message.")


class ActivityItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    actorId = serializers.CharField(allow_null=True)
    action = serializers.CharField()
    entityType = serializers.CharField(allow_null=True)
    entityId = serializers.CharField(allow_null=True)
    data = serializers.JSONField()
    createdAt = serializers.DateTimeField()


class ActivityPageSerializer(serializers.Serializer):
    items = ActivityItemSerializer(many=True)
    nextCursor = serializers.IntegerField(
        allow_null=True,
        help_text="Pass as `before` to read the next page. `null` on the last page.",
    )
