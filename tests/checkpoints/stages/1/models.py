from django.db import models


class Account(models.Model):
    name = models.CharField(max_length=80)
    opened = models.DateTimeField(auto_now_add=True)


class Tag(models.Model):
    label = models.CharField(max_length=40, unique=True)


class Entry(models.Model):
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="entries")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    note = models.CharField(max_length=200, blank=True, default="")
    tags = models.ManyToManyField(Tag, blank=True)
