from django.db import models


class LiveManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)


class Category(models.Model):
    name = models.CharField(max_length=100)
    is_deleted = models.BooleanField(default=False)

    objects = LiveManager()
    all_objects = models.Manager()


class Item(models.Model):
    name = models.CharField(max_length=100)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="items")
    labels = models.ManyToManyField(Category, blank=True, related_name="labelled_items")
    is_deleted = models.BooleanField(default=False)

    objects = LiveManager()
    all_objects = models.Manager()
