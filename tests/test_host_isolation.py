"""A failure inside DBS never takes the developer's project down with it."""

import logging
import threading

import pytest
from django.contrib import admin
from django.contrib.auth import authenticate
from django.contrib.auth.models import Group, User
from django.core import checks
from django.db import DatabaseError, transaction
from django.http import HttpResponse
from django.test import Client, RequestFactory
from django.urls import path

from dbs import schedule_runner
from dbs.models import AuditEvent
from dbs.security import detector, guard, middleware

SITE = "/shop/"
BROKEN = "/admin/broken/"
ADMIN_PAGE = "/admin/auth/group/"
ADD_GROUP = "/admin/auth/group/add/"
GUARD = "/admin/dbs/panel/guard/"
SETUP = "/admin/dbs/panel/setup/"
CONFIGURE = {
    "level": "balanced",
    "expected_networks": "",
    "trusted_networks": "127.0.0.0/8",
    "notify_emails": "",
}


class DevelopersBug(Exception):
    pass


def shop(request):
    return HttpResponse("the developer's page")


def broken(request):
    raise DevelopersBug("the developer's own bug")


urlpatterns = [
    path("shop/", shop),
    path("admin/broken/", broken),
    path("admin/", admin.site.urls),
]

pytestmark = pytest.mark.urls(__name__)


@pytest.fixture(autouse=True)
def clean_detector():
    detector.forget()
    yield
    detector.forget()


@pytest.fixture
def root(db):
    return User.objects.create_superuser("root", "root@example.com", "pw")


@pytest.fixture
def panel(root):
    client = Client()
    client.force_login(root)
    client.post(SETUP, CONFIGURE)
    return client


def failing(error):
    def fail(*args, **kwargs):
        raise error

    return fail


def test_a_guard_that_cannot_decide_leaves_the_rest_of_the_site_alone(panel, monkeypatch):
    monkeypatch.setattr(guard, "is_locked_out", failing(DatabaseError("no such table")))

    response = panel.get(SITE)

    assert response.status_code == 200
    assert response.content == b"the developer's page"


def test_a_guard_that_cannot_decide_keeps_the_admin_readable(panel, monkeypatch, caplog):
    monkeypatch.setattr(guard, "evaluate", failing(DatabaseError("the database went away")))

    with caplog.at_level(logging.ERROR, logger="dbs"):
        response = panel.get(ADMIN_PAGE)

    assert response.status_code == 200
    assert "the database went away" in caplog.text
    assert "could not check GET /admin/auth/group/" in caplog.text


def test_a_guard_that_cannot_decide_refuses_changes_and_downloads(panel, monkeypatch):
    monkeypatch.setattr(guard, "evaluate", failing(DatabaseError("the database went away")))

    added = panel.post(ADD_GROUP, {"name": "intruders"})
    exported = panel.get("/admin/dbs/backuprecord/1/download/")

    assert added.status_code == exported.status_code == 503
    assert added.content.decode() == middleware.UNDECIDED
    assert not Group.objects.filter(name="intruders").exists()


def test_the_guard_poller_hears_a_refusal_as_try_again_later(panel, monkeypatch):
    monkeypatch.setattr(guard, "evaluate", failing(RuntimeError("scoring broke")))

    response = panel.post(GUARD, "{}", content_type="application/json")

    assert response.status_code == 503
    assert response.json() == {
        "authorized": False,
        "action": "refused",
        "reasons": [middleware.UNDECIDED],
        "poll_after": middleware.RETRY_SECONDS,
    }


def test_a_session_the_guard_could_not_end_is_refused_even_for_reading(panel, monkeypatch):
    monkeypatch.setattr(guard, "evaluate", lambda *args, **kwargs: guard.Verdict(guard.BLOCK))
    monkeypatch.setattr(guard, "apply", failing(DatabaseError("cannot write the lockout")))

    response = panel.get(ADMIN_PAGE)

    assert response.status_code == 403
    assert response.content.decode() == middleware.UNENDED


def test_a_locked_out_session_whose_logout_fails_is_refused(panel, monkeypatch):
    monkeypatch.setattr(guard, "is_locked_out", lambda user: True)
    monkeypatch.setattr(middleware, "logout", failing(DatabaseError("the session store failed")))

    response = panel.get(SITE)

    assert response.status_code == 403


def test_a_poller_that_cannot_be_added_leaves_the_page_as_it_was(panel, monkeypatch, settings):
    settings.DBS_GUARD_EVERYWHERE = True
    monkeypatch.setattr(middleware, "_poller_tag", failing(RuntimeError("no static files")))

    response = panel.get(ADMIN_PAGE)

    assert response.status_code == 200
    assert b"dbs-guard" not in response.content


def test_the_developers_own_errors_still_reach_django(panel):
    with pytest.raises(DevelopersBug):
        panel.get(BROKEN)


def test_a_sign_in_failure_the_trail_cannot_record_still_just_fails(root, monkeypatch, caplog):
    monkeypatch.setattr(AuditEvent.objects, "create", failing(DatabaseError("read-only")))
    request = RequestFactory().post("/admin/login/")

    with caplog.at_level(logging.WARNING, logger="dbs"), transaction.atomic():
        assert authenticate(request, username="root", password="wrong") is None
        assert User.objects.filter(username="root").exists()

    assert "auth.failed" in caplog.text and "read-only" in caplog.text


def test_a_sign_in_failure_dbs_cannot_read_still_just_fails(root, monkeypatch, caplog):
    from dbs.security import signals

    monkeypatch.setattr(signals, "client_address", failing(RuntimeError("odd request")))
    request = RequestFactory().post("/admin/login/")

    with caplog.at_level(logging.ERROR, logger="dbs"):
        assert authenticate(request, username="root", password="wrong") is None

    assert "could not record a failed sign-in" in caplog.text


def test_a_scheduler_thread_that_cannot_start_never_fails_a_request(
    root, settings, monkeypatch, caplog
):
    class Refused:
        def __init__(self, target, name, daemon):
            pass

        def start(self):
            raise RuntimeError("can't start new thread")

    settings.DBS_SCHEDULER = "thread"
    monkeypatch.setitem(schedule_runner._started_in, "pid", None)
    monkeypatch.setattr(schedule_runner.threading, "Thread", Refused)
    client = Client()

    with caplog.at_level(logging.ERROR, logger="dbs"):
        response = client.get(SITE)

    assert response.status_code == 200
    assert "runs no scheduled backups" in caplog.text


def test_a_scikit_learn_that_breaks_on_import_turns_the_model_off(monkeypatch, caplog):
    def broken_import(name):
        raise ValueError("numpy.dtype size changed, may indicate binary incompatibility")

    monkeypatch.setattr(detector.importlib, "import_module", broken_import)
    monkeypatch.setattr(detector, "_import_failure_reported", threading.Event())

    with caplog.at_level(logging.WARNING, logger="dbs"):
        assert detector.model_available() is False
        assert detector.model_available() is False

    assert caplog.text.count("scikit-learn failed to import") == 1


def test_network_settings_the_guard_ignores_are_reported(settings):
    from dbs.security.checks import check_session_guard

    settings.DBS_TRUSTED_PROXIES = ["10.0.0.0/24", "10.0.0.0/33", "0.0.0.0/0"]
    settings.DBS_TRUSTED_NETWORKS = "192.168.1.0/24"

    found = [entry for entry in check_session_guard() if entry.id == "dbs.security.W004"]

    assert len(found) == 1
    assert found[0].level == checks.WARNING
    assert "DBS_TRUSTED_PROXIES" in found[0].msg
    assert "'10.0.0.0/33'" in found[0].msg and "'0.0.0.0/0'" in found[0].msg
    assert "10.0.0.0/24'" not in found[0].msg
