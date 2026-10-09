from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from dbs.manager.activity.repositories import ActivityRepository
from dbs.manager.backups.repositories import BackupPlanRepository
from dbs.manager.servers.services import ServerService
from tests.manager.servers.support import PASSWORD

PLANS = "/api/backups/plans/"

SHAPE = {
    "id",
    "server",
    "name",
    "kind",
    "paths",
    "pattern",
    "interval_minutes",
    "keep",
    "keep_remote",
    "enabled",
    "next_run_at",
    "last_run_at",
    "last_status",
    "last_error_code",
    "created_at",
}


def url(plan) -> str:
    return f"{PLANS}{plan.pk}/"


def logged(action: str):
    return list(ActivityRepository().filtered(action=action))


def body(server, **fields) -> dict:
    return {
        "server": str(server.pk),
        "name": "django-dbs",
        "kind": "dbs",
        "account_password": PASSWORD,
    } | fields


def about(moment: str | None, expected) -> bool:
    return abs(parse_datetime(moment) - expected) < timedelta(seconds=5)


@pytest.fixture
def other_server(admin, server):
    return ServerService(admin).create(
        name="web-2",
        host="10.0.0.6",
        username="deploy",
        auth_method="password",
        password="ssh-password",
        host_key=server.host_key,
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", ""),
        ("post", ""),
        ("get", "{id}/"),
        ("patch", "{id}/"),
        ("delete", "{id}/"),
        ("post", "{id}/run/"),
    ],
)
def test_every_plan_endpoint_needs_a_session(anonymous, method, path):
    response = getattr(anonymous, method)(PLANS + path.format(id=uuid4()))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "not_authenticated"


@pytest.mark.django_db
def test_the_list_needs_a_server(api):
    missing = api.get(PLANS)
    malformed = api.get(PLANS, {"server": "web-1"})

    assert missing.status_code == malformed.status_code == 400
    assert missing.json()["error"]["fields"] == {"server": ["required"]}
    assert malformed.json()["error"]["fields"] == {"server": ["invalid"]}


@pytest.mark.django_db
def test_the_list_is_one_servers_plans_by_name_and_paginated(
    api, admin, other_server, make_plan
):
    weekly = make_plan(name="weekly", interval_minutes=10080)
    daily = make_plan(name="daily")
    make_plan(server=other_server.pk, name="elsewhere")
    gone = make_plan(name="also-daily")
    api.delete(url(gone))

    first = api.get(PLANS, {"server": weekly.server_id, "page_size": 1}).json()
    second = api.get(
        PLANS, {"server": weekly.server_id, "page_size": 1, "page": 2}
    ).json()

    assert first["count"] == 2
    assert first["previous"] is None and first["next"] is not None
    assert [row["id"] for row in first["results"]] == [str(daily.pk)]
    assert [row["id"] for row in second["results"]] == [str(weekly.pk)]
    assert api.get(PLANS, {"server": uuid4()}).json()["count"] == 0


@pytest.mark.django_db
def test_a_new_plan_has_the_documented_shape_and_runs_one_interval_from_now(
    api, admin, server
):
    response = api.post(
        PLANS, body(server, interval_minutes=360, keep=14, keep_remote=0, enabled=True)
    )

    assert response.status_code == 201
    plan = response.json()
    assert set(plan) == SHAPE
    assert plan["server"] == str(server.pk)
    assert (plan["name"], plan["kind"], plan["interval_minutes"]) == (
        "django-dbs",
        "dbs",
        360,
    )
    assert (plan["keep"], plan["keep_remote"], plan["enabled"]) == (14, 0, True)
    assert about(plan["next_run_at"], timezone.now() + timedelta(hours=6))
    assert (plan["last_run_at"], plan["last_status"], plan["last_error_code"]) == (
        None,
        "none",
        "",
    )
    [entry] = logged("plan.create")
    assert (entry.subject, entry.target_name, entry.actor) == (
        str(server.pk),
        "django-dbs",
        admin,
    )
    assert entry.data == {}
    assert str(BackupPlanRepository().get(plan["id"])) == "django-dbs"


@pytest.mark.django_db
def test_left_out_fields_take_the_models_defaults(api, server):
    plan = api.post(PLANS, body(server)).json()

    assert (plan["interval_minutes"], plan["next_run_at"]) == (None, None)
    assert (plan["keep"], plan["keep_remote"], plan["enabled"]) == (7, 1, True)


@pytest.mark.django_db
def test_a_disabled_plan_has_no_next_run(api, server):
    plan = api.post(PLANS, body(server, interval_minutes=60, enabled=False)).json()

    assert plan["next_run_at"] is None


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("fields", "errors"),
    [
        ({"interval_minutes": 30}, {"interval_minutes": ["invalid_interval"]}),
        ({"interval_minutes": 0}, {"interval_minutes": ["invalid_interval"]}),
        ({"interval_minutes": -60}, {"interval_minutes": ["invalid_interval"]}),
        ({"keep": 0}, {"keep": ["min_value"]}),
        ({"keep": 366}, {"keep": ["max_value"]}),
        ({"keep_remote": -1}, {"keep_remote": ["min_value"]}),
        ({"keep_remote": 366}, {"keep_remote": ["max_value"]}),
        ({"kind": "zip"}, {"kind": ["invalid_choice"]}),
        ({"name": ""}, {"name": ["blank"]}),
        ({"name": "x" * 101}, {"name": ["max_length"]}),
    ],
)
def test_a_plan_that_does_not_validate_is_refused_and_not_logged(
    api, server, fields, errors
):
    response = api.post(PLANS, body(server, **fields))

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid"
    assert response.json()["error"]["fields"] == errors
    assert logged("plan.create") == []


@pytest.mark.django_db
def test_a_plan_needs_a_server_a_name_and_a_kind(api):
    response = api.post(PLANS, {})

    assert response.status_code == 400
    assert response.json()["error"]["fields"] == {
        "name": ["required"],
        "server": ["required"],
        "kind": ["required"],
    }


@pytest.mark.django_db
def test_a_name_is_unique_among_a_servers_plans_that_are_not_deleted(
    api, other_server, make_plan
):
    taken = make_plan()

    refused = api.post(PLANS, body(taken.server))
    elsewhere = api.post(PLANS, body(other_server))
    api.delete(url(taken))
    again = api.post(PLANS, body(taken.server))

    assert refused.status_code == 400
    assert refused.json()["error"]["fields"] == {"name": ["name_taken"]}
    assert elsewhere.status_code == again.status_code == 201


@pytest.mark.django_db
def test_a_name_taken_between_the_check_and_the_write_is_still_name_taken(
    api, monkeypatch, make_plan
):
    taken = make_plan()
    monkeypatch.setattr(
        BackupPlanRepository,
        "name_in_use",
        lambda self, server_id, name, excluding=None: False,
    )

    response = api.post(PLANS, body(taken.server))

    assert response.status_code == 400
    assert response.json()["error"]["fields"] == {"name": ["name_taken"]}
    refused, made = logged("plan.create")
    assert (refused.status, refused.error_code) == ("failed", "name_taken")
    assert made.status == "succeeded"


@pytest.mark.django_db
def test_both_service_errors_are_reported_together(api, make_plan):
    taken = make_plan()

    response = api.post(PLANS, body(taken.server, interval_minutes=5))

    assert response.json()["error"]["fields"] == {
        "name": ["name_taken"],
        "interval_minutes": ["invalid_interval"],
    }


@pytest.mark.django_db
def test_a_plan_for_an_unknown_or_deleted_server_is_not_found(api, admin, server):
    ServerService(admin).delete(server.pk)

    for server_id in (server.pk, uuid4()):
        response = api.post(
            PLANS, {"server": str(server_id), "name": "p", "kind": "dbs"}
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"
    assert logged("plan.create") == []


@pytest.mark.django_db
def test_one_plan_reads_as_the_list_shows_it(api, make_plan):
    plan = make_plan()
    [listed] = api.get(PLANS, {"server": plan.server_id}).json()["results"]

    response = api.get(url(plan))

    assert response.status_code == 200
    assert response.json() == listed


@pytest.mark.django_db
def test_an_unknown_or_deleted_plan_is_not_found(api, make_plan):
    plan = make_plan()
    api.delete(url(plan))

    for plan_id in (plan.pk, uuid4()):
        for method in ("get", "patch", "delete"):
            response = getattr(api, method)(f"{PLANS}{plan_id}/")
            assert response.status_code == 404
            assert response.json()["error"]["code"] == "not_found"


@pytest.mark.django_db
def test_a_change_touches_only_what_was_sent_and_logs_what_changed(
    api, admin, server, other_server, make_plan
):
    plan = make_plan()

    response = api.patch(
        url(plan),
        {
            "name": "nightly",
            "keep": 7,
            "keep_remote": 3,
            "server": str(other_server.pk),
        },
    )

    assert response.status_code == 200
    changed = response.json()
    assert (changed["name"], changed["keep"], changed["keep_remote"]) == (
        "nightly",
        7,
        3,
    )
    assert changed["server"] == str(server.pk)
    assert changed["interval_minutes"] == 1440
    [entry] = logged("plan.update")
    assert (entry.subject, entry.target_name, entry.actor) == (
        str(server.pk),
        "nightly",
        admin,
    )
    assert entry.data == {"fields": ["keep_remote", "name"]}


@pytest.mark.django_db
def test_a_rename_keeps_the_schedule(api, make_plan):
    plan = make_plan()
    stored = BackupPlanRepository().get(plan.pk).next_run_at

    api.patch(url(plan), {"name": "nightly"})

    assert BackupPlanRepository().get(plan.pk).next_run_at == stored


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("change", "next_run"),
    [
        ({"interval_minutes": 60}, timedelta(hours=1)),
        ({"interval_minutes": None}, None),
        ({"enabled": False}, None),
    ],
)
def test_a_new_interval_or_switching_off_reschedules_from_now(
    api, make_plan, change, next_run
):
    plan = make_plan()
    BackupPlanRepository().update(
        plan, next_run_at=timezone.now() + timedelta(minutes=3)
    )

    changed = api.patch(url(plan), change).json()

    if next_run is None:
        assert changed["next_run_at"] is None
    else:
        assert about(changed["next_run_at"], timezone.now() + next_run)


@pytest.mark.django_db
def test_switching_a_plan_back_on_schedules_it_one_interval_from_now(api, make_plan):
    plan = make_plan(enabled=False, interval_minutes=720)

    changed = api.patch(url(plan), {"enabled": True}).json()

    assert about(changed["next_run_at"], timezone.now() + timedelta(hours=12))


@pytest.mark.django_db
def test_a_change_is_validated_like_a_new_plan(api, make_plan):
    plan = make_plan()
    other = make_plan(name="weekly", interval_minutes=10080)

    renamed = api.patch(url(other), {"name": "django-dbs"})
    same = api.patch(url(plan), {"name": "django-dbs"})
    interval = api.patch(url(plan), {"interval_minutes": 45})
    keep = api.patch(url(plan), {"keep": 0})

    assert renamed.json()["error"]["fields"] == {"name": ["name_taken"]}
    assert same.status_code == 200
    assert interval.json()["error"]["fields"] == {
        "interval_minutes": ["invalid_interval"]
    }
    assert keep.json()["error"]["fields"] == {"keep": ["min_value"]}
    assert [entry.data for entry in logged("plan.update")] == [{"fields": []}]


@pytest.mark.django_db
def test_a_deleted_plan_is_hidden_and_its_backups_keep_its_name(
    api, admin, server, make_plan, ran
):
    plan = make_plan()
    ran(plan)

    response = api.delete(url(plan))

    assert response.status_code == 204
    assert api.get(PLANS, {"server": server.pk}).json()["count"] == 0
    [backup] = api.get("/api/backups/", {"server": server.pk}).json()["results"]
    assert (backup["plan"], backup["plan_name"]) == (str(plan.pk), "django-dbs")
    [entry] = logged("plan.delete")
    assert (entry.subject, entry.target_name, entry.actor) == (
        str(server.pk),
        "django-dbs",
        admin,
    )


def archive_body(server, **fields) -> dict:
    return body(server, name="files", kind="archive", paths=["/srv/app/media"]) | fields


@pytest.mark.django_db
def test_an_archive_plan_keeps_its_paths_normalised_and_once_each(api, server):
    response = api.post(
        PLANS,
        archive_body(
            server, paths=["/srv/app/media/", "//srv/app/./media", "/etc/app.conf", "/"]
        ),
        format="json",
    )

    assert response.status_code == 201
    assert (response.json()["kind"], response.json()["paths"]) == (
        "archive",
        ["/srv/app/media", "/etc/app.conf", "/"],
    )
    assert BackupPlanRepository().get(response.json()["id"]).paths == [
        "/srv/app/media",
        "/etc/app.conf",
        "/",
    ]


@pytest.mark.django_db
def test_a_dbs_plan_has_no_paths(api, server):
    sent_none = api.post(PLANS, body(server), format="json")
    sent_empty = api.post(PLANS, body(server, name="other", paths=[]), format="json")

    assert sent_none.json()["paths"] == sent_empty.json()["paths"] == []


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("fields", "errors"),
    [
        ({"paths": []}, {"paths": ["paths_required"]}),
        ({"paths": ["srv/app"]}, {"paths": ["absolute_path_required"]}),
        ({"paths": ["/srv/app", "/srv/../etc"]}, {"paths": ["absolute_path_required"]}),
        ({"paths": [""]}, {"paths": ["absolute_path_required"]}),
        ({"paths": ["   "]}, {"paths": ["absolute_path_required"]}),
        ({"paths": ["/srv/a\x00b"]}, {"paths": ["null_characters_not_allowed"]}),
        ({"paths": ["/x" * 513]}, {"paths": ["max_length"]}),
        ({"paths": [f"/srv/{n}" for n in range(51)]}, {"paths": ["max_length"]}),
        ({"paths": "/srv/app"}, {"paths": ["not_a_list"]}),
        ({"paths": None}, {"paths": ["null"]}),
    ],
)
def test_an_archive_plan_with_paths_that_will_not_do_is_refused(
    api, server, fields, errors
):
    response = api.post(PLANS, archive_body(server, **fields), format="json")

    assert response.status_code == 400
    assert response.json()["error"]["fields"] == errors
    assert logged("plan.create") == []


@pytest.mark.django_db
def test_an_archive_plan_needs_its_paths(api, server):
    sent = archive_body(server)
    del sent["paths"]

    response = api.post(PLANS, sent, format="json")

    assert response.json()["error"]["fields"] == {"paths": ["paths_required"]}


@pytest.mark.django_db
def test_fifty_paths_are_enough(api, server):
    response = api.post(
        PLANS,
        archive_body(server, paths=[f"/srv/{n}" for n in range(50)]),
        format="json",
    )

    assert response.status_code == 201
    assert len(response.json()["paths"]) == 50


@pytest.mark.django_db
def test_a_dbs_plan_given_paths_is_refused(api, server):
    response = api.post(PLANS, body(server, paths=["/srv/app"]), format="json")

    assert response.status_code == 400
    assert response.json()["error"]["fields"] == {"paths": ["paths_not_allowed"]}


@pytest.mark.django_db
def test_an_archive_plans_paths_change_and_are_logged(api, admin, server, make_plan):
    plan = make_plan(name="files", kind="archive", paths=["/srv/app/media"])

    response = api.patch(
        url(plan),
        {"paths": ["/etc/", "/srv/app/media"], "account_password": PASSWORD},
        format="json",
    )
    kept = api.patch(url(plan), {"keep": 3}, format="json")

    assert response.status_code == 200
    assert response.json()["paths"] == ["/etc", "/srv/app/media"]
    assert kept.json()["paths"] == ["/etc", "/srv/app/media"]
    assert [entry.data for entry in logged("plan.update")] == [
        {"fields": ["keep"]},
        {"fields": ["paths"]},
    ]


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("paths", "code"),
    [([], "paths_required"), (["relative"], "absolute_path_required")],
)
def test_an_archive_plans_paths_are_validated_on_change(api, make_plan, paths, code):
    plan = make_plan(name="files", kind="archive", paths=["/srv/app/media"])

    response = api.patch(url(plan), {"paths": paths}, format="json")

    assert response.json()["error"]["fields"] == {"paths": [code]}
    assert BackupPlanRepository().get(plan.pk).paths == ["/srv/app/media"]


@pytest.mark.django_db
def test_a_dbs_plan_takes_no_paths_on_change_and_keeps_its_kind(api, make_plan):
    plan = make_plan()

    refused = api.patch(url(plan), {"paths": ["/srv"]}, format="json")
    empty = api.patch(url(plan), {"paths": [], "kind": "archive"}, format="json")

    assert refused.json()["error"]["fields"] == {"paths": ["paths_not_allowed"]}
    assert empty.status_code == 200
    assert (empty.json()["kind"], empty.json()["paths"]) == ("dbs", [])
    assert [entry.data for entry in logged("plan.update")] == [{"fields": []}]


def collect_body(server, **fields) -> dict:
    return (
        body(server, name="pg-dumps", kind="collect", paths=["/var/backups/pg"])
        | fields
    )


@pytest.mark.django_db
def test_a_collect_plan_keeps_one_folder_and_a_pattern_and_no_copy_on_the_server(
    api, server
):
    response = api.post(
        PLANS,
        collect_body(
            server, paths=["//var/backups/./pg/"], pattern="*.sql.gz", keep_remote=3
        ),
        format="json",
    )

    assert response.status_code == 201
    plan = response.json()
    assert set(plan) == SHAPE
    assert (plan["kind"], plan["paths"], plan["pattern"]) == (
        "collect",
        ["/var/backups/pg"],
        "*.sql.gz",
    )
    assert plan["keep_remote"] == 0
    stored = BackupPlanRepository().get(plan["id"])
    assert (stored.paths, stored.pattern, stored.keep_remote) == (
        ["/var/backups/pg"],
        "*.sql.gz",
        0,
    )


@pytest.mark.django_db
def test_a_collect_plan_sent_no_pattern_takes_every_file(api, server):
    response = api.post(PLANS, collect_body(server), format="json")

    assert (response.json()["pattern"], response.json()["keep_remote"]) == ("*", 0)


@pytest.mark.django_db
def test_two_spellings_of_one_folder_are_one_folder(api, server):
    response = api.post(
        PLANS,
        collect_body(server, paths=["/var/backups/pg", "/var/backups/pg/"]),
        format="json",
    )

    assert response.status_code == 201
    assert response.json()["paths"] == ["/var/backups/pg"]


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("fields", "errors"),
    [
        ({"paths": []}, {"paths": ["paths_required"]}),
        ({"paths": ["var/backups"]}, {"paths": ["absolute_path_required"]}),
        ({"paths": ["/var/backups/../etc"]}, {"paths": ["absolute_path_required"]}),
        ({"paths": ["/var/backups/pg", "/srv"]}, {"paths": ["one_folder_required"]}),
        ({"pattern": ""}, {"pattern": ["invalid_pattern"]}),
        ({"pattern": "   "}, {"pattern": ["invalid_pattern"]}),
        ({"pattern": "pg/*.sql.gz"}, {"pattern": ["invalid_pattern"]}),
        ({"pattern": "*" * 201}, {"pattern": ["invalid_pattern"]}),
        ({"pattern": "a\x00b"}, {"pattern": ["null_characters_not_allowed"]}),
        ({"pattern": None}, {"pattern": ["null"]}),
        (
            {"paths": ["/a", "/b"], "pattern": "x/y"},
            {"paths": ["one_folder_required"], "pattern": ["invalid_pattern"]},
        ),
    ],
)
def test_a_collect_plan_that_will_not_do_is_refused(api, server, fields, errors):
    response = api.post(PLANS, collect_body(server, **fields), format="json")

    assert response.status_code == 400
    assert response.json()["error"]["fields"] == errors
    assert logged("plan.create") == []


@pytest.mark.django_db
def test_a_collect_plan_needs_its_folder(api, server):
    sent = collect_body(server)
    del sent["paths"]

    response = api.post(PLANS, sent, format="json")

    assert response.json()["error"]["fields"] == {"paths": ["paths_required"]}


@pytest.mark.django_db
def test_two_hundred_characters_are_enough_for_a_pattern(api, server):
    response = api.post(PLANS, collect_body(server, pattern="?" * 200), format="json")

    assert response.status_code == 201


@pytest.mark.django_db
@pytest.mark.parametrize(
    "fields",
    [{"kind": "dbs"}, {"kind": "archive", "paths": ["/srv/app/media"]}],
    ids=["dbs", "archive"],
)
def test_a_pattern_means_nothing_to_the_other_kinds(api, server, fields):
    response = api.post(
        PLANS, body(server, pattern="*.sql.gz", **fields), format="json"
    )

    assert response.status_code == 201
    assert response.json()["pattern"] == ""


@pytest.mark.django_db
def test_a_collect_plans_folder_and_pattern_change_and_its_server_copies_do_not(
    api, admin, server, make_plan
):
    plan = make_plan(name="pg-dumps", kind="collect", paths=["/var/backups/pg"])

    pattern = api.patch(
        url(plan), {"pattern": "*.dump", "account_password": PASSWORD}, format="json"
    )
    folder = api.patch(
        url(plan),
        {"paths": ["/srv/dumps/"], "keep_remote": 5, "account_password": PASSWORD},
        format="json",
    )

    assert pattern.json()["pattern"] == "*.dump"
    assert (folder.json()["paths"], folder.json()["keep_remote"]) == (["/srv/dumps"], 0)
    assert [entry.data for entry in logged("plan.update")] == [
        {"fields": ["paths"]},
        {"fields": ["pattern"]},
    ]


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("change", "errors"),
    [
        ({"paths": []}, {"paths": ["paths_required"]}),
        ({"paths": ["/a", "/b"]}, {"paths": ["one_folder_required"]}),
        ({"pattern": ""}, {"pattern": ["invalid_pattern"]}),
        ({"pattern": "../*"}, {"pattern": ["invalid_pattern"]}),
    ],
)
def test_a_collect_plan_is_validated_on_change(api, make_plan, change, errors):
    plan = make_plan(name="pg-dumps", kind="collect", paths=["/var/backups/pg"])

    response = api.patch(url(plan), change, format="json")

    assert response.json()["error"]["fields"] == errors
    stored = BackupPlanRepository().get(plan.pk)
    assert (stored.paths, stored.pattern) == (["/var/backups/pg"], "*")


@pytest.mark.django_db
def test_a_pattern_sent_to_another_kind_is_not_a_change(api, make_plan):
    plan = make_plan()

    response = api.patch(url(plan), {"pattern": "*.sql.gz"}, format="json")

    assert response.json()["pattern"] == ""
    assert [entry.data for entry in logged("plan.update")] == [{"fields": []}]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "fields",
    [
        {"kind": "archive", "paths": ["/srv/app"]},
        {"kind": "collect", "paths": ["/srv/dumps"], "pattern": "*.sql.gz"},
    ],
)
def test_a_plan_that_reads_the_server_needs_the_users_password(api, server, fields):
    missing = api.post(
        PLANS, body(server, account_password="", **fields), format="json"
    )
    wrong = api.post(
        PLANS, body(server, account_password="wrong", **fields), format="json"
    )

    assert missing.status_code == wrong.status_code == 400
    assert missing.json()["error"]["fields"] == {"account_password": ["required"]}
    assert wrong.json()["error"]["code"] == "invalid_password"
    assert api.get(PLANS, {"server": server.pk}).json()["count"] == 0
    [refused] = logged("plan.create")
    assert (refused.status, refused.error_code) == ("failed", "invalid_password")


@pytest.mark.django_db
def test_a_dbs_plan_needs_no_password(api, server):
    response = api.post(PLANS, body(server, account_password=""))

    assert response.status_code == 201


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("made", "change"),
    [
        ({"kind": "archive", "paths": ["/srv/app"]}, {"paths": ["/etc"]}),
        ({"kind": "collect", "paths": ["/srv/dumps"]}, {"paths": ["/etc"]}),
        ({"kind": "collect", "paths": ["/srv/dumps"]}, {"pattern": ".env*"}),
    ],
)
def test_changing_what_a_plan_reads_needs_the_users_password(
    api, make_plan, made, change
):
    plan = make_plan(**made)

    missing = api.patch(url(plan), change, format="json")
    wrong = api.patch(url(plan), change | {"account_password": "wrong"}, format="json")
    right = api.patch(url(plan), change | {"account_password": PASSWORD}, format="json")

    assert missing.json()["error"]["fields"] == {"account_password": ["required"]}
    assert wrong.json()["error"]["code"] == "invalid_password"
    assert right.status_code == 200
    statuses = [(entry.status, entry.error_code) for entry in logged("plan.update")]
    assert statuses == [("succeeded", ""), ("failed", "invalid_password")]


@pytest.mark.django_db
def test_the_rest_of_a_plan_that_reads_the_server_changes_without_one(api, make_plan):
    plan = make_plan(kind="archive", paths=["/srv/app"])

    response = api.patch(
        url(plan),
        {
            "name": "nightly",
            "paths": ["/srv/app"],
            "interval_minutes": 60,
            "keep": 3,
            "keep_remote": 0,
            "enabled": False,
        },
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["name"] == "nightly"
