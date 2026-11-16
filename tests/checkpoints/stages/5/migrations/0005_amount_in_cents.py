from django.db import migrations, models


def to_cents(apps, schema_editor):
    Entry = apps.get_model("ledger", "Entry")
    entries = Entry.objects.using(schema_editor.connection.alias)
    for entry in entries.all():
        entries.filter(pk=entry.pk).update(amount_cents=int(entry.amount * 10))


class Migration(migrations.Migration):
    dependencies = [("ledger", "0004_owner_memo_receipt")]

    operations = [
        migrations.AddField(
            model_name="entry", name="amount_cents", field=models.IntegerField(default=0)
        ),
        migrations.RunPython(to_cents),
        migrations.RemoveField(model_name="entry", name="amount"),
    ]
