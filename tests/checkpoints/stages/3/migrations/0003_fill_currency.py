from django.db import migrations


def fill(apps, schema_editor):
    Account = apps.get_model("ledger", "Account")
    Account.objects.using(schema_editor.connection.alias).filter(currency="").update(
        currency="USD"
    )


class Migration(migrations.Migration):
    dependencies = [("ledger", "0002_account_currency")]

    operations = [migrations.RunPython(fill, migrations.RunPython.noop)]
