from django.urls import path

from dbs.manager.accounts.views import (
    CsrfView,
    EnrollmentConfirmView,
    EnrollmentView,
    MeView,
    PasswordView,
    RecoveryCodesView,
    SignInView,
    SignOutView,
    TwoFactorView,
)

app_name = "accounts"

urlpatterns = [
    path("csrf/", CsrfView.as_view(), name="csrf"),
    path("login/", SignInView.as_view(), name="login"),
    path("two-factor/", TwoFactorView.as_view(), name="two-factor"),
    path("two-factor/enrollment/", EnrollmentView.as_view(), name="enrollment"),
    path(
        "two-factor/enrollment/confirm/",
        EnrollmentConfirmView.as_view(),
        name="enrollment-confirm",
    ),
    path("logout/", SignOutView.as_view(), name="logout"),
    path("me/", MeView.as_view(), name="me"),
    path("password/", PasswordView.as_view(), name="password"),
    path("recovery-codes/", RecoveryCodesView.as_view(), name="recovery-codes"),
]
