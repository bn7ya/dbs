from django.db import models


class Blob(models.Model):
    name = models.CharField(max_length=50)
    data = models.BinaryField(null=True)
    text = models.TextField(blank=True)
