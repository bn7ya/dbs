import os

from django.db import models

TABLES = int(os.environ.get("DBS_SCALE_TABLES", "1000"))
FOREIGN_KEY_EVERY = 10
MANY_TO_MANY_EVERY = 50


def table(index):
    attributes = {
        "__module__": __name__,
        "name": models.CharField(max_length=40),
        "value": models.IntegerField(default=0),
        "Meta": type("Meta", (), {"app_label": "scaleapp", "db_table": f"scale_t{index:04d}"}),
    }
    if index and index % FOREIGN_KEY_EVERY == 0:
        attributes["parent"] = models.ForeignKey(
            f"scaleapp.Table{index - 1:04d}",
            null=True,
            on_delete=models.CASCADE,
            related_name="+",
        )
    if index and index % MANY_TO_MANY_EVERY == 0:
        attributes["peers"] = models.ManyToManyField(
            f"scaleapp.Table{index - 1:04d}", related_name="+"
        )
    return type(f"Table{index:04d}", (models.Model,), attributes)


TABLE_MODELS = [table(index) for index in range(TABLES)]
globals().update({model.__name__: model for model in TABLE_MODELS})


class Wide(models.Model):
    name = models.CharField(max_length=60)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    created = models.DateTimeField()
    note = models.TextField(blank=True)
    flag = models.BooleanField(default=False)

    class Meta:
        app_label = "scaleapp"
