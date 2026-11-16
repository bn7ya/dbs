import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Account",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=80)),
                ("opened", models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.CreateModel(
            name="Tag",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("label", models.CharField(max_length=40, unique=True)),
            ],
        ),
        migrations.CreateModel(
            name="Entry",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=10)),
                ("note", models.CharField(blank=True, default="", max_length=200)),
                (
                    "account",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="entries",
                        to="ledger.account",
                    ),
                ),
                ("tags", models.ManyToManyField(blank=True, to="ledger.tag")),
            ],
        ),
    ]
