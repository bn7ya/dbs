from __future__ import annotations

import pytest

from dbs.manager.activity.repositories import ActivityRepository
from dbs.manager.applications import deployment
from dbs.manager.applications.models import Application
from dbs.manager.applications.serializers import ApplicationUpdateSerializer
from tests.manager.factories import make_application

LIST = "/api/applications/"
COMPOSE_ON_POSTGRES = {
    "runs_in": "compose",
    "engine": "docker",
    "database": "postgresql",
    "database_runs": "compose",
    "settings_from": "folder_env",
    "source": "git",
}


def test_cleaned_drops_not_sure_and_keeps_known_answers():
    assert deployment.cleaned({"runs_in": "compose", "engine": "", "database": None}) == {
        "runs_in": "compose"
    }


@pytest.mark.parametrize(
    "answers",
    [{"runs_in": "kubernetes"}, {"favourite": "docker"}, {"engine": "docker; id"}],
)
def test_cleaned_refuses_unknown_questions_and_answers(answers):
    with pytest.raises(ValueError):
        deployment.cleaned(answers)


def test_mismatches_name_each_answer_that_disagrees_with_what_was_found():
    found = {"runs_in": "host", "engine": "docker", "database": "mysql"}

    assert deployment.mismatches(COMPOSE_ON_POSTGRES, found) == [
        {"field": "runs_in", "said": "compose", "found": "host"},
        {"field": "database", "said": "postgresql", "found": "mysql"},
    ]


def test_mariadb_and_mysql_agree_because_django_names_both_mysql():
    assert deployment.mismatches({"database": "mariadb"}, {"database": "mysql"}) == []
    assert deployment.agreements({"database": "mariadb"}, {"database": "mysql"}) == 1


def test_an_unanswered_question_never_counts_as_a_mismatch():
    assert deployment.mismatches({}, {"runs_in": "host"}) == []
    assert deployment.mismatches({"runs_in": "host"}, {}) == []


def test_effective_prefers_what_was_found_over_what_was_said():
    assert deployment.effective(
        {"runs_in": "compose", "web_server": "nginx"}, {"runs_in": "host", "engine": ""}
    ) == {"runs_in": "host", "web_server": "nginx"}


def test_the_serializer_refuses_a_question_it_does_not_know():
    payload = ApplicationUpdateSerializer(
        data={"deployment": {"runs_in": "compose", "favourite": "docker"}}, partial=True
    )

    assert not payload.is_valid()
    assert "favourite" in payload.errors["deployment"]


def test_the_serializer_refuses_an_answer_it_does_not_know():
    payload = ApplicationUpdateSerializer(
        data={"deployment": {"database": "oracle"}}, partial=True
    )

    assert not payload.is_valid()
    assert "database" in payload.errors["deployment"]


@pytest.mark.django_db
def test_an_application_keeps_its_answers(admin, server):
    application = make_application(
        admin, server=server, name="shop", deployment=COMPOSE_ON_POSTGRES
    )

    assert Application.objects.get(pk=application.pk).deployment == COMPOSE_ON_POSTGRES


@pytest.mark.django_db
def test_changing_the_answers_needs_no_password_at_any_time(api, application):
    response = api.patch(
        f"{LIST}{application.pk}/",
        {"deployment": {"runs_in": "host", "web_server": "nginx", "engine": ""}},
        format="json",
    )

    assert response.status_code == 200, response.json()
    assert response.json()["deployment"] == {"runs_in": "host", "web_server": "nginx"}
    [entry] = ActivityRepository().filtered(action="application.update")
    assert entry.data == {"fields": ["deployment"]}


@pytest.mark.django_db
def test_answers_come_back_with_the_application(api, admin, server):
    application = make_application(
        admin, server=server, name="shop", deployment={"source": "git"}
    )

    response = api.get(f"{LIST}{application.pk}/")

    assert response.json()["deployment"] == {"source": "git"}
