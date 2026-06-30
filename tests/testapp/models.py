"""Sample models exercising FK, M2M, FileField and a FILE_PATH string field."""

from django.db import models


class Author(models.Model):
    name = models.CharField(max_length=200)

    def __str__(self):
        return self.name


class Tag(models.Model):
    label = models.CharField(max_length=100)

    def __str__(self):
        return self.label


class Book(models.Model):
    title = models.CharField(max_length=300)
    author = models.ForeignKey(Author, on_delete=models.CASCADE, related_name="books")
    tags = models.ManyToManyField(Tag, blank=True, related_name="books")
    cover = models.FileField(upload_to="covers/", blank=True)
    # A plain string column that happens to hold a path to an external file. DBS
    # backs up the file's *contents* because it is mapped as FieldType.FILE_PATH.
    sidecar_path = models.CharField(max_length=500, blank=True, default="")

    def __str__(self):
        return self.title
