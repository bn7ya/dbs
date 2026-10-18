from django.db import models


class Customer(models.Model):
    name = models.CharField(max_length=80)
    created = models.DateTimeField(auto_now_add=True)


class Order(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="orders")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    note = models.TextField(blank=True)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)
