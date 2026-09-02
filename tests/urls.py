"""Test URLConf wiring the Django admin and the optional DBS contrib views."""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("dbs/", include("dbs.contrib.urls")),
]
