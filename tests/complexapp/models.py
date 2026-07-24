import uuid

from django.db import models


class Publisher(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name_en = models.CharField(max_length=200)
    name_ar = models.CharField(max_length=200)
    established = models.DateField()
    metadata = models.JSONField(default=dict)
    active = models.BooleanField(default=True)


class Branch(models.Model):
    publisher = models.ForeignKey(Publisher, on_delete=models.CASCADE, related_name="branches")
    code = models.CharField(max_length=20)
    city_en = models.CharField(max_length=100)
    city_ar = models.CharField(max_length=100)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["publisher", "code"], name="uniq_branch_code")]


class Employee(models.Model):
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="employees")
    manager = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="reports")
    full_name_en = models.CharField(max_length=200)
    full_name_ar = models.CharField(max_length=200)
    salary = models.DecimalField(max_digits=10, decimal_places=2)
    hired_at = models.DateTimeField()
    bio = models.TextField(blank=True)
    badge = models.BinaryField(default=bytes)

    class Meta:
        indexes = [models.Index(fields=["branch", "hired_at"], name="idx_emp_branch_hired")]


class EmployeeProfile(models.Model):
    employee = models.OneToOneField(Employee, on_delete=models.CASCADE, related_name="profile")
    slug = models.SlugField(max_length=100, unique=True)
    preferences = models.JSONField(default=dict)


class Writer(models.Model):
    name_en = models.CharField(max_length=200)
    name_ar = models.CharField(max_length=200)
    penname = models.CharField(max_length=100, unique=True)


class Keyword(models.Model):
    word_en = models.CharField(max_length=100)
    word_ar = models.CharField(max_length=100, unique=True)


class Series(models.Model):
    publisher = models.ForeignKey(Publisher, null=True, blank=True, on_delete=models.SET_NULL, related_name="series")
    title_en = models.CharField(max_length=300)
    title_ar = models.CharField(max_length=300)


class Volume(models.Model):
    series = models.ForeignKey(Series, on_delete=models.CASCADE, related_name="volumes")
    writer = models.ForeignKey(Writer, on_delete=models.CASCADE, related_name="volumes")
    editors = models.ManyToManyField(Writer, through="EditingAssignment", related_name="edited_volumes")
    keywords = models.ManyToManyField(Keyword, blank=True, related_name="volumes")
    isbn = models.CharField(max_length=20, unique=True)
    position = models.PositiveIntegerField()
    price = models.DecimalField(max_digits=8, decimal_places=2)
    published = models.DateTimeField()
    summary = models.JSONField(default=dict)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["series", "position"], name="uniq_volume_position")]


class EditingAssignment(models.Model):
    volume = models.ForeignKey(Volume, on_delete=models.CASCADE, related_name="assignments")
    writer = models.ForeignKey(Writer, on_delete=models.CASCADE, related_name="assignments")
    role = models.CharField(max_length=50)
    started = models.DateField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["volume", "writer", "role"], name="uniq_assignment")]


class Review(models.Model):
    volume = models.ForeignKey(Volume, on_delete=models.CASCADE, related_name="reviews")
    reviewer_name = models.CharField(max_length=200)
    rating = models.PositiveIntegerField()
    comment = models.TextField()
    created = models.DateTimeField()
