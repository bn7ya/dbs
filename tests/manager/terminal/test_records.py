import os

import pytest

from dbs.manager.activity.services import ActivityService
from dbs.manager.envfiles.models import EnvVersion
from tests.manager.deploy.test_deploy import AFTER, ready_to_deploy
from tests.manager.servers.support import PASSWORD
from tests.manager.support import logged
from tests.manager.test_redeploy import (  # noqa: F401
    TARGET_ENV,
    failing_migration,
    world,
)

ENV = b"SECRET_KEY=first\nDEBUG=0\n"


@pytest.fixture(autouse=True)
def umask():
    before = os.umask(0o022)
    yield
    os.umask(before)


@pytest.fixture
def project(tmp_path):
    root = tmp_path.resolve() / "srv" / "app"
    (root / "media").mkdir(parents=True)
    (root / ".env").write_bytes(ENV)
    return root


@pytest.fixture
def application(make_application, project):
    return make_application(
        env_path=str(project / ".env"), file_roots=[str(project / "media")]
    )


@pytest.mark.django_db
def test_env_pull_list_compare_reveal_and_push(
    terminal, admin, application, project, local_host
):
    assert "Kept a new version" in terminal("env", "pull", "web-1").out
    (project / ".env").write_bytes(b"SECRET_KEY=second\nNEW=1\n")
    assert terminal("env", "pull", "web-1").code == 0

    versions = terminal("env", "list", "web-1", "--json").json()
    newest, oldest = versions[0]["id"], versions[1]["id"]
    compared = terminal("env", "compare", oldest, newest, "--json").json()
    assert compared["added"] == ["NEW"] and compared["removed"] == ["DEBUG"]
    assert compared["changed"] == ["SECRET_KEY"]

    assert terminal("env", "reveal", oldest).code == 1
    shown = terminal("env", "reveal", oldest, "--password-stdin", stdin=f"{PASSWORD}\n")
    assert shown.out == ENV.decode()

    pushed = terminal("env", "push", oldest, "--password-stdin", stdin=f"{PASSWORD}\n")
    assert pushed.code == 0, pushed.err
    assert (project / ".env").read_bytes() == ENV
    assert EnvVersion.objects.filter(source=EnvVersion.Source.PUSHED).exists()
    assert {version.application_id for version in EnvVersion.objects.all()} == {
        application.pk
    }


@pytest.mark.django_db
def test_files_list_upload_download_mkdir_and_delete(
    terminal, admin, application, project, local_host, tmp_path
):
    media = project / "media"
    local = tmp_path / "logo.png"
    local.write_bytes(b"logo")

    assert terminal("files", "upload", "web-1", media, local).code == 0
    assert (media / "logo.png").read_bytes() == b"logo"
    assert terminal("files", "mkdir", "web-1", media, "thumbs").code == 0
    listed = terminal("files", "list", "web-1", "--json").json()
    assert {entry["name"] for entry in listed["results"]} == {"logo.png", "thumbs"}

    copy = tmp_path / "copy.png"
    assert (
        terminal("files", "download", "web-1", media / "logo.png", "-o", copy).code == 0
    )
    assert copy.read_bytes() == b"logo"

    assert terminal("files", "delete", "web-1", media / "logo.png").code == 1
    assert terminal("files", "delete", "web-1", media / "logo.png", "--yes").code == 0
    assert not (media / "logo.png").exists()


@pytest.mark.django_db
def test_files_outside_the_roots_stay_closed(
    terminal, admin, application, local_host, tmp_path
):
    ran = terminal("files", "list", "web-1", tmp_path)

    assert ran.code == 1


@pytest.mark.django_db(transaction=True)
def test_redeploy_rehearses_and_prints_each_step(terminal, admin, world):  # noqa: F811
    ran = terminal(
        "redeploy",
        "start",
        "--from",
        "web-1",
        "--to",
        "web-2",
        "--backup",
        world["backup"].pk,
    )

    assert ran.code == 0, ran.out + ran.err
    assert "check" in ran.out and "Rehearsed moving web-1 onto web-2." in ran.out
    assert [
        "--dry-run" in restore["argv"] for restore in world["sent"]["restores"]
    ] == [True]


@pytest.mark.django_db(transaction=True)
def test_a_move_that_stops_names_the_step_and_the_revert(terminal, admin, world):  # noqa: F811
    failing_migration(world)

    ran = terminal(
        "redeploy",
        "start",
        "--from",
        "web-1",
        "--to",
        "web-2",
        "--env",
        world["version"].pk,
        "--real",
        "--confirm-name",
        "web-2",
        "--password-stdin",
        stdin=f"{PASSWORD}\n",
    )

    assert ran.code == 1
    assert "Stopped at migrate." in ran.out
    move = logged("redeploy.run")[0].pk
    assert f"django_dbs redeploy revert {move} --real" in ran.out

    reverted = terminal(
        "redeploy",
        "revert",
        move,
        "--real",
        "--confirm-name",
        "web-2",
        "--password-stdin",
        stdin=f"{PASSWORD}\n",
    )

    assert reverted.code == 0, reverted.out + reverted.err
    assert "Reverted web-2." in reverted.out
    assert world["env"].read_bytes() == TARGET_ENV


@pytest.mark.django_db
def test_only_a_move_or_a_deploy_can_be_reverted(terminal, admin, world):  # noqa: F811
    ran = terminal("redeploy", "revert", "nope")
    assert ran.code == 1 and "'nope' is not a move number." in ran.err

    entry = ActivityService(admin).record("auth.sign_in", target="sara")
    ran = terminal("redeploy", "revert", entry.pk)
    assert ran.code == 1 and f"{entry.pk} is not a move or a deploy." in ran.err


@pytest.mark.django_db
def test_a_real_redeploy_needs_the_target_name_and_password(terminal, admin, world):  # noqa: F811
    ran = terminal(
        "redeploy",
        "start",
        "--from",
        "web-1",
        "--to",
        "web-2",
        "--backup",
        world["backup"].pk,
        "--real",
        "--confirm-name",
        "web-2",
        "--password-stdin",
        stdin="wrong\n",
    )

    assert ran.code == 1
    assert world["sent"]["restores"] == []


@pytest.mark.django_db(transaction=True)
def test_app_deploy_rehearses_and_prints_each_step(terminal, admin, world):  # noqa: F811
    ready_to_deploy(world)

    ran = terminal("app", "deploy", "web-2")

    assert ran.code == 0, ran.out + ran.err
    assert "git_pull" in ran.out and "Rehearsed deploying web-2." in ran.out
    assert world["sent"]["taken"] == []


@pytest.mark.django_db(transaction=True)
def test_a_real_app_deploy_needs_the_name_and_the_password(terminal, admin, world):  # noqa: F811
    ready_to_deploy(world)

    refused = terminal("app", "deploy", "web-2", "--real")
    ran = terminal(
        "app",
        "deploy",
        "web-2",
        "--real",
        "--confirm-name",
        "web-2",
        "--password-stdin",
        stdin=f"{PASSWORD}\n",
    )

    assert refused.code == 1
    assert ran.code == 0, ran.out + ran.err
    assert "Deployed web-2." in ran.out
    [job] = logged("redeploy.deploy")
    assert job.data["after"] == {"git_head": AFTER}


@pytest.mark.django_db
def test_deploy_steps_are_shown_and_set_from_a_file(
    terminal, admin, world, tmp_path  # noqa: F811
):
    empty = terminal("app", "deploy-steps", "web-2")
    chosen = tmp_path / "steps.json"
    chosen.write_text('[{"kind": "migrate"}, {"kind": "collectstatic"}]')
    saved = terminal(
        "app",
        "deploy-steps",
        "web-2",
        "--set",
        str(chosen),
        "--password-stdin",
        stdin=f"{PASSWORD}\n",
    )
    shown = terminal("app", "deploy-steps", "web-2", "--json").json()

    assert "web-2 has no deploy steps yet." in empty.out
    assert saved.code == 0, saved.err
    assert "collectstatic" in saved.out
    assert [step["kind"] for step in shown] == ["migrate", "collectstatic"]


@pytest.mark.django_db
def test_deploy_steps_from_an_unreadable_file_are_refused(
    terminal, admin, world, tmp_path  # noqa: F811
):
    broken = tmp_path / "steps.json"
    broken.write_text("[{")

    ran = terminal("app", "deploy-steps", "web-2", "--set", str(broken))

    assert ran.code == 1 and "cannot read" in ran.err
