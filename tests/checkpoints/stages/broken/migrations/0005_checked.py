from django.db import migrations, models


def fail(apps, schema_editor):
    raise RuntimeError("this migration is broken")


class Migration(migrations.Migration):
    dependencies = [("ledger", "0004_owner_memo_receipt")]

    operations = [
        migrations.AddField(
            model_name="entry", name="checked", field=models.BooleanField(default=False)
        ),
        migrations.RunPython(fail),
    ]
