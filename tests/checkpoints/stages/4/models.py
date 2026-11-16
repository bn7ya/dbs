from django.conf import settings
from django.db import models


class Account(models.Model):
    name = models.CharField(max_length=80)
    opened = models.DateTimeField(auto_now_add=True)
    currency = models.CharField(max_length=3, blank=True, default="")
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )


class Tag(models.Model):
    label = models.CharField(max_length=40, unique=True)


class Entry(models.Model):
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="entries")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    memo = models.CharField(max_length=200, blank=True, default="")
    tags = models.ManyToManyField(Tag, blank=True)


class Receipt(models.Model):
    entry = models.OneToOneField(Entry, on_delete=models.CASCADE)
    number = models.CharField(max_length=20, unique=True)
