# `apps.backoffice` se retira y se parte en `apps.audit` y `apps.dashboard`.
#
# Los dos permisos que colgaban de `backoffice.activitylog` cambian de dueño
# sin cambiar el codename del panel:
# - `activity.view` -> `audit.activitylog` (`view_activitylog`).
# - `dashboard.view` -> `tt_auth.user` (`view_dashboard`); `dashboard` no
#   tiene modelos, ver el comentario en `User.Meta`.
#
# Cada Role y Group que tenía el permiso viejo recibe el nuevo antes de
# borrar el ContentType de `backoffice`, así los Roles conservan lo que
# concedían. En una base nueva no existe ese ContentType y no hace nada.
from django.db import migrations

OLD_CONTENT_TYPE = ("backoffice", "activitylog")
NEW_OWNERS = {
    "view_dashboard": ("tt_auth", "user"),
    "view_activitylog": ("audit", "activitylog"),
}


def move_backoffice_permissions(apps, schema_editor):
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")
    Group = apps.get_model("auth", "Group")
    Role = apps.get_model("tt_auth", "Role")

    old_content_type = ContentType.objects.filter(
        app_label=OLD_CONTENT_TYPE[0], model=OLD_CONTENT_TYPE[1]
    ).first()
    if old_content_type is None:
        return

    for old in Permission.objects.filter(content_type=old_content_type):
        owner = NEW_OWNERS.get(old.codename)
        if owner is None:
            continue
        content_type, _ = ContentType.objects.get_or_create(
            app_label=owner[0], model=owner[1]
        )
        new, _ = Permission.objects.get_or_create(
            content_type=content_type,
            codename=old.codename,
            defaults={"name": old.name},
        )
        for role in Role.objects.filter(permissions=old):
            role.permissions.add(new)
        for group in Group.objects.filter(permissions=old):
            group.permissions.add(new)

    # Borrar el ContentType arrastra sus permisos y los enlaces de Role/Group.
    old_content_type.delete()


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("tt_auth", "0010_cache_table"),
        ("audit", "0001_initial"),
        ("auth", "0001_initial"),
        ("contenttypes", "0001_initial"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="user",
            options={
                "db_table": "users",
                "default_permissions": (),
                "permissions": [
                    ("manage_users", "Can manage users"),
                    ("view_dashboard", "Can view dashboard"),
                ],
            },
        ),
        migrations.RunPython(move_backoffice_permissions, noop_reverse),
    ]
