from django.urls import path

from dbs.manager.accounts.views import (
    AccountDetailView,
    AccountListView,
    HandOverView,
    PasswordExpireView,
    TwoFactorResetView,
)

app_name = "account_management"

urlpatterns = [
    path("", AccountListView.as_view(), name="list"),
    path("<int:pk>/", AccountDetailView.as_view(), name="detail"),
    path(
        "<int:pk>/two-factor/reset/",
        TwoFactorResetView.as_view(),
        name="two-factor-reset",
    ),
    path(
        "<int:pk>/password/expire/",
        PasswordExpireView.as_view(),
        name="password-expire",
    ),
    path("<int:pk>/master/", HandOverView.as_view(), name="master"),
]
