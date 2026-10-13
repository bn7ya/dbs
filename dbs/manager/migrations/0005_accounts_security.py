import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.utils import timezone

MASTER = "master"
ADMIN = "admin"


def assign_roles(apps, schema_editor):
    User = apps.get_model(*settings.AUTH_USER_MODEL.split("."))
    Account = apps.get_model("dbs_manager", "Account")
    now = timezone.now()
    users = list(User.objects.order_by("-is_active", "date_joined", "pk"))
    for position, user in enumerate(users):
        Account.objects.get_or_create(
            user_id=user.pk,
            defaults={
                "role": MASTER if position == 0 else ADMIN,
                "password_changed_at": now,
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("dbs_manager", "0004_backupfile_failure"),
    ]

    operations = [
        migrations.CreateModel(
            name="Account",
            fields=[
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        related_name="manager_account",
                        serialize=False,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "role",
                    models.CharField(
                        choices=[
                            ("master", "Master"),
                            ("admin", "Admin"),
                            ("operator", "Operator"),
                            ("viewer", "Viewer"),
                        ],
                        default="viewer",
                        max_length=16,
                    ),
                ),
                (
                    "password_changed_at",
                    models.DateTimeField(default=timezone.now),
                ),
                ("password_change_required", models.BooleanField(default=False)),
                ("totp_secret_sealed", models.BinaryField(editable=False, null=True)),
                ("totp_enrolled_at", models.DateTimeField(blank=True, null=True)),
                ("totp_last_step", models.BigIntegerField(blank=True, null=True)),
            ],
            options={
                "ordering": ("user__username",),
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(("role", "master")),
                        fields=("role",),
                        name="dbs_manager_account_one_master",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="RecoveryCode",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("digest", models.CharField(max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("used_at", models.DateTimeField(blank=True, null=True)),
                (
                    "account",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="recovery_codes",
                        to="dbs_manager.account",
                    ),
                ),
            ],
            options={
                "ordering": ("created_at", "id"),
                "indexes": [
                    models.Index(
                        fields=["account", "digest"], name="dbs_manager_recovery_idx"
                    )
                ],
            },
        ),
        migrations.RunPython(assign_roles, migrations.RunPython.noop),
    ]
