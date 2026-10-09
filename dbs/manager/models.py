from django.db import models


class ScheduledTask(models.Model):
    name = models.CharField(max_length=64, primary_key=True)
    next_run_at = models.DateTimeField()

    class Meta:
        ordering = ("next_run_at", "name")

    def __str__(self):
        return f"{self.name} at {self.next_run_at:%Y-%m-%d %H:%M}"
