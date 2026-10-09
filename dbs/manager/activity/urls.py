from django.urls import path

from dbs.manager.activity.views import ActivityDetailView, ActivityListView

app_name = "activity"

urlpatterns = [
    path("", ActivityListView.as_view(), name="list"),
    path("<int:pk>/", ActivityDetailView.as_view(), name="detail"),
]
