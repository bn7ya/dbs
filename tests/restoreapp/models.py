from django.db import models


class Place(models.Model):
    name = models.CharField(max_length=100)
    featured = models.ForeignKey(
        "Restaurant",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="featured_in",
    )


class Restaurant(Place):
    serves_pizza = models.BooleanField(default=False)


class Bar(Place):
    taps = models.PositiveIntegerField(default=0)


class Pizzeria(Restaurant):
    oven = models.CharField(max_length=50, default="wood")


class Venue(models.Model):
    name = models.CharField(max_length=100)

    class Meta:
        managed = False
        db_table = "restoreapp_external_venue"


class Account(models.Model):
    name = models.CharField(max_length=100)
    tenant = models.CharField(max_length=20)
    api_token = models.IntegerField()
    note = models.CharField(max_length=100, default="fresh")
    members = models.ManyToManyField("Member", blank=True, related_name="accounts")


class Member(models.Model):
    name = models.CharField(max_length=100)
