"""Test URLConf wiring in the optional DBS admin views."""

from django.urls import include, path

urlpatterns = [
    path("dbs/", include("dbs.contrib.urls")),
]
