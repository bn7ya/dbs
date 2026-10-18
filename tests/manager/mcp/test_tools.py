import ast
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from django.utils import timezone

from dbs.manager.applications.models import Application
from dbs.manager.applications.repositories import ApplicationRepository
from dbs.manager.backups.locks import TakeLock
from dbs.manager.backups.models import BackupFile, BackupPlan
from dbs.manager.envfiles.models import EnvVersion
from dbs.manager.mcp import tools
from dbs.manager.mcp.server import NEEDS_PASSWORD
from dbs.manager.servers.gateways import parse_host_key
from dbs.manager.servers.models import Server
from dbs.manager.servers.repositories import ServerRepository
from dbs.manager.servers.services import (
    HostKeyConfirmationService,
    ServerConnectionService,
)
from tests.manager.backups.support import BackupHost, server_tree
from tests.manager.servers.support import (
    BACKUP_DIR,
    BACKUP_PASSPHRASE,
    ENV_PATH,
    PROJECT_DIR,
    PYTHON,
    SETTINGS_MODULE,
    SSH_PASSWORD,
    Result,
    connecting_to,
    host_key_line,
    private_key_text,
)
from tests.manager.support import logged
from tests.manager.terminal.test_servers import (
    REMOTE_VERSION,
    open_to_others,
    ready_remote,
)
from tests.manager.test_redeploy import failing_migration, for_real, world  # noqa: F401

CONNECT = "dbs.manager.servers.services.connection_service.connect"
FETCH_HOST_KEY = "dbs.manager.servers.services.server_service.fetch_host_key"
RUNS_JOBS = pytest.mark.django_db(transaction=True)
SETUP_OVER = timedelta(hours=2)
FORBIDDEN = (
    "reveal",
    "push",
    "remove",
    "delete",
    "repin",
    "host_key_change",
    "real",
    "confirm",
    "reject",
    "shell",
    "terminal",
    "console",
    "exec",
    "pty",
    "pause",
)
FORBIDDEN_PROPERTIES = {
    "account_password",
    "rehearse",
    "rehearsal",
    "real",
    "host_key",
    "backup_passphrase",
    "steps",
    "line",
}
SHELL_MODULE_WORDS = ("console", "shell", "terminal", "subprocess", "pexpect")
TOOLS = {
    "manager_overview",
    "list_servers",
    "get_server",
    "browse_server",
    "fingerprint_host",
    "add_server",
    "update_server",
    "check_servers",
    "list_applications",
    "get_application",
    "discover_applications",
    "add_application",
    "update_application",
    "check_applications",
    "capture_passphrase",
    "list_backups",
    "take_backups",
    "verify_backup",
    "rehearse_restore",
    "download_backup",
    "list_plans",
    "get_plan",
    "add_plan",
    "update_plan",
    "run_plan",
    "list_activity",
    "get_activity",
    "list_env_versions",
    "pull_env",
    "compare_env_versions",
    "list_files",
    "rehearse_redeploy",
    "rehearse_revert",
}
ENV = b"SECRET_KEY=sk_live_very_secret\nDEBUG=0\n"


@pytest.fixture
def offered(monkeypatch):
    line = host_key_line()
    monkeypatch.setattr(FETCH_HOST_KEY, lambda host, port: parse_host_key(line))
    return line


@pytest.fixture
def remote(monkeypatch):
    found = ready_remote()
    monkeypatch.setattr(CONNECT, connecting_to(found))
    return found


@pytest.fixture
def host(monkeypatch, tmp_path):
    root = tmp_path / "server"
    server_tree(root)
    found = BackupHost(root=root)
    monkeypatch.setattr(CONNECT, connecting_to(found))
    return found


def confirmed(mcp, admin, host="10.0.0.5", port=22):
    held = mcp("fingerprint_host", host=host, port=port).data
    HostKeyConfirmationService(admin).confirm(held["id"])
    return held["id"]


def tool_list(mcp):
    return mcp.server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})[
        "result"
    ]["tools"]


def imported_modules(path: Path) -> list[str]:
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = "." * node.level + (node.module or "")
            found.append(base)
            found += [f"{base}.{alias.name}" for alias in node.names]
    return found


def shell_like(module: str) -> bool:
    return any(
        part == "pty" or any(word in part for word in SHELL_MODULE_WORDS)
        for part in module.lower().split(".")
    )


def settled(model):
    repository = (
        ServerRepository() if isinstance(model, Server) else ApplicationRepository()
    )
    return repository.update(model, created_at=timezone.now() - SETUP_OVER)


@pytest.mark.django_db
def test_every_tool_has_a_closed_schema_and_destroys_nothing(mcp):
    for tool in tool_list(mcp):
        schema = tool["inputSchema"]
        assert schema["type"] == "object" and schema["additionalProperties"] is False
        assert set(schema["required"]) <= set(schema["properties"])
        assert all(
            "type" in prop or "enum" in prop for prop in schema["properties"].values()
        )
        assert tool["annotations"]["destructiveHint"] is False
        assert tool["description"]


@pytest.mark.django_db
def test_the_toolbox_is_the_servers_and_applications_one(mcp):
    assert {tool["name"] for tool in tool_list(mcp)} == TOOLS


@pytest.mark.django_db
def test_no_tool_reveals_restores_for_real_removes_deletes_or_opens_a_shell(mcp):
    tools_listed = tool_list(mcp)

    names = [tool["name"] for tool in tools_listed]
    assert not [name for name in names if any(word in name for word in FORBIDDEN)]
    for tool in tools_listed:
        properties = set(tool["inputSchema"]["properties"])
        assert not properties & FORBIDDEN_PROPERTIES, tool["name"]
        if tool["name"] != "add_server":
            assert not properties & {"password", "key_passphrase"}, tool["name"]


def test_the_toolbox_imports_no_console_or_shell_module():
    modules = imported_modules(Path(tools.__file__))

    assert "dbs.manager.adapters" in modules
    assert not [module for module in modules if shell_like(module)]


def test_a_shell_module_would_be_noticed():
    assert shell_like("dbs.manager.terminal.session")
    assert shell_like("dbs.manager.servers.services.console_service")
    assert shell_like("pty") and shell_like("subprocess")
    assert not shell_like("dbs.manager.adapters.problems")


@pytest.mark.django_db
def test_reading_tools_return_what_the_api_returns(mcp, api, make_application):
    application = make_application()
    make_application(name="blog", host="10.0.0.6")

    listed = mcp("list_servers").data["results"]
    shown = mcp("get_server", server="web-1").data
    applications = mcp("list_applications").data["results"]
    on_web_1 = mcp("list_applications", server="web-1").data["results"]
    shown_application = mcp("get_application", application="web-1").data

    assert listed == api.get("/api/servers/").json()["results"]
    assert shown == api.get(f"/api/servers/{application.server_id}/").json()
    assert applications == api.get("/api/applications/").json()["results"]
    assert [row["name"] for row in applications] == ["blog", "web-1"]
    assert (
        on_web_1
        == (
            api.get(f"/api/applications/?server={application.server_id}").json()[
                "results"
            ]
        )
    )
    assert [row["name"] for row in on_web_1] == ["web-1"]
    assert shown_application == (api.get(f"/api/applications/{application.pk}/").json())
    assert BACKUP_PASSPHRASE not in mcp("get_application", application="web-1").raw
    assert mcp("manager_overview").data == api.get("/api/dashboard/").json()


@pytest.mark.django_db
def test_adding_a_server_with_a_password_pins_the_key_and_checks_it(
    mcp, admin, offered, remote
):
    confirmation = confirmed(mcp, admin, port=2222)
    added = mcp(
        "add_server",
        name="web-1",
        host="10.0.0.5",
        port=2222,
        username="deploy",
        confirmation=confirmation,
        auth_method="password",
        password=SSH_PASSWORD,
    )

    assert added.ok, added.text
    assert added.data["check"]["status"] == Server.CheckStatus.OK
    assert set(added.data["engines"]) == {"docker", "podman"}
    assert SSH_PASSWORD not in added.raw
    server = ServerRepository().active().get()
    assert server.host_key == offered
    assert ServerConnectionService(admin).credentials(server).password == SSH_PASSWORD
    assert [entry.actor for entry in logged("server.create")] == [admin]
    assert not ApplicationRepository().active().exists()
    assert logged("application.discover") == []
    assert not [run for run in remote.runs if PYTHON in run["argv"]]


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("setting", "value"), [("project_dir", PROJECT_DIR), ("discover", False)]
)
def test_adding_a_server_takes_no_application_settings(
    mcp, admin, offered, setting, value
):
    added = mcp(
        "add_server",
        name="web-1",
        host="10.0.0.5",
        username="deploy",
        confirmation=confirmed(mcp, admin),
        auth_method="generate_key",
        **{setting: value},
    )

    assert not added.ok and added.text == f"add_server takes no {setting}."
    assert not Server.objects.exists()


@pytest.mark.django_db
def test_adding_with_a_key_file_reads_the_file_and_never_returns_it(
    mcp, admin, offered, remote, tmp_path
):
    key = tmp_path / "id_ed25519"
    key.write_text(private_key_text())

    added = mcp(
        "add_server",
        name="web-1",
        host="10.0.0.5",
        username="deploy",
        confirmation=confirmed(mcp, admin),
        auth_method="key_file",
        key_file=str(key),
    )

    assert added.ok, added.text
    assert "PRIVATE KEY" not in added.raw
    server = ServerRepository().active().get()
    assert (
        ServerConnectionService(admin).credentials(server).private_key
        == key.read_text()
    )


@pytest.mark.django_db
def test_adding_with_a_new_key_returns_the_authorized_keys_line(mcp, admin, offered):
    added = mcp(
        "add_server",
        name="web-1",
        host="10.0.0.5",
        username="deploy",
        confirmation=confirmed(mcp, admin),
        auth_method="generate_key",
    )

    assert added.data["authorized_keys_hint"].endswith("~deploy/.ssh/authorized_keys")
    assert "PRIVATE KEY" not in added.raw


@pytest.mark.django_db
def test_adding_reports_the_apis_validation(mcp, admin, make_server, offered):
    make_server(name="web-1")

    added = mcp(
        "add_server",
        name="web-1",
        host="10.0.0.6",
        username="deploy",
        confirmation=confirmed(mcp, admin, host="10.0.0.6"),
        auth_method="generate_key",
    )

    assert not added.ok and added.text.startswith("name: ")


@pytest.mark.django_db
def test_check_servers_names_the_container_engines(mcp, make_server, monkeypatch):
    make_server()
    found = ready_remote()
    found.answers[("docker", "version", "--format", "{{.Server.Version}}")] = Result(
        0, "27.1.1\n"
    )
    monkeypatch.setattr(CONNECT, connecting_to(found))

    [checked] = mcp("check_servers", all=True).data["results"]

    assert checked["status"] == Server.CheckStatus.OK and checked["problem"] == ""
    assert checked["engines"]["docker"]["usable"] is True
    assert checked["engines"]["podman"]["installed"] is False
    assert (
        mcp("check_servers").text == "name at least one server, or choose all of them."
    )


@pytest.mark.django_db
def test_discover_applications_lists_what_it_found_like_the_api(
    mcp, api, make_server, remote
):
    server = make_server()

    found = mcp("discover_applications", server="web-1", folder=PROJECT_DIR)

    assert found.ok, found.text
    answer = api.post(
        "/api/applications/discover/",
        {"server": str(server.pk), "folder": PROJECT_DIR},
        format="json",
    )
    assert found.data == answer.json()
    [candidate] = found.data["candidates"]
    assert (candidate["kind"], candidate["project_dir"]) == ("host", PROJECT_DIR)
    assert (candidate["python_path"], candidate["dbs_version"]) == (
        PYTHON,
        REMOTE_VERSION,
    )
    assert candidate["settings_module"] == SETTINGS_MODULE
    assert candidate["backup_dir_on_host"] == BACKUP_DIR
    assert candidate["problems"] == [] and candidate["compatible"] is True
    assert not ApplicationRepository().active().exists()


@pytest.mark.django_db
def test_discover_applications_without_a_folder_suggests_folders(
    mcp, make_server, remote
):
    make_server()

    found = mcp("discover_applications", server="web-1")

    assert found.ok, found.text
    assert found.data["candidates"] == []
    assert PROJECT_DIR in found.data["folders"]


@pytest.mark.django_db
def test_add_application_adds_the_candidate_and_checks_it(
    mcp, admin, make_server, remote
):
    server = make_server()

    added = mcp("add_application", server="web-1", folder=PROJECT_DIR, name="shop")

    assert added.ok, added.text
    assert added.data["name"] == "shop"
    assert added.data["candidate"]["python_path"] == PYTHON
    assert added.data["check"] == {"status": Application.CheckStatus.OK, "problem": ""}
    assert added.data["compatible"] is True
    assert BACKUP_PASSPHRASE not in added.raw
    application = ApplicationRepository().active().get()
    assert application.server_id == server.pk
    assert (application.project_dir, application.python_path) == (PROJECT_DIR, PYTHON)
    assert (application.settings_module, application.env_path) == (
        SETTINGS_MODULE,
        ENV_PATH,
    )
    assert application.discovered_at is not None and application.has_backup_passphrase
    assert [entry.actor for entry in logged("application.create")] == [admin]


@pytest.mark.django_db
def test_settings_passed_to_add_application_replace_what_was_found(
    mcp, make_server, remote
):
    make_server()

    added = mcp(
        "add_application",
        server="web-1",
        folder=PROJECT_DIR,
        name="shop",
        settings_module="config.settings.staging",
        file_roots=["/srv/app/media"],
    )

    assert added.ok, added.text
    assert added.data["check"]["status"] == Application.CheckStatus.PROBLEM
    assert added.data["check"]["problem"] == "/srv/app/media is missing"
    application = ApplicationRepository().active().get()
    assert application.settings_module == "config.settings.staging"
    assert application.file_roots == ["/srv/app/media"]


@pytest.mark.django_db
@pytest.mark.parametrize("candidate", [0, 2])
def test_a_candidate_that_was_not_found_is_a_clear_error(
    mcp, make_server, remote, candidate
):
    make_server()

    added = mcp(
        "add_application",
        server="web-1",
        folder=PROJECT_DIR,
        name="shop",
        candidate=candidate,
    )

    assert not added.ok and added.text == "choose a candidate from 1 to 1."
    assert not ApplicationRepository().active().exists()


@pytest.mark.django_db
def test_add_application_in_a_folder_without_a_project_adds_nothing(
    mcp, make_server, remote
):
    make_server()

    added = mcp("add_application", server="web-1", folder="/srv/empty", name="shop")

    assert not added.ok
    assert added.text == "found no Django project in /srv/empty."
    assert not ApplicationRepository().active().exists()


@pytest.mark.django_db
def test_nothing_is_run_in_a_folder_others_can_write_to(mcp, make_server, remote):
    make_server()
    open_to_others(remote)

    found = mcp("discover_applications", server="web-1", folder=PROJECT_DIR)
    added = mcp("add_application", server="web-1", folder=PROJECT_DIR, name="shop")

    assert found.ok, found.text
    assert found.data["trusted"] is False and found.data["candidates"] == []
    assert not added.ok
    assert added.text == (
        f"{PROJECT_DIR} or its parent can be written by others, so nothing in it "
        "was run."
    )
    assert remote.runs == []
    assert not ApplicationRepository().active().exists()


@pytest.mark.django_db
def test_looking_on_a_settled_server_needs_the_account_password(
    mcp, make_server, remote
):
    settled(make_server())

    found = mcp("discover_applications", server="web-1", folder=PROJECT_DIR)
    added = mcp("add_application", server="web-1", folder=PROJECT_DIR, name="shop")

    assert not found.ok and found.text == NEEDS_PASSWORD
    assert not added.ok and added.text == NEEDS_PASSWORD
    assert remote.runs == []
    assert not ApplicationRepository().active().exists()


@pytest.mark.django_db
def test_check_applications_reports_each_and_what_is_wrong(
    mcp, make_application, remote
):
    make_application(name="shop")
    make_application(name="blog", host="10.0.0.6", python_path="python3")

    results = mcp("check_applications", all=True).data["results"]
    named = mcp("check_applications", applications=["shop"]).data["results"]

    assert [(item["name"], item["status"]) for item in results] == [
        ("blog", Application.CheckStatus.PROBLEM),
        ("shop", Application.CheckStatus.OK),
    ]
    assert f"set the application's Python to {PYTHON}" in results[0]["problem"]
    assert results[1]["remote_version"] == REMOTE_VERSION
    assert [item["name"] for item in named] == ["shop"]
    assert (
        mcp("check_applications").text
        == "name at least one application, or choose all of them."
    )


@pytest.mark.django_db
def test_list_applications_filters_by_server_and_name(mcp, make_application):
    make_application(name="shop", host="10.0.0.5")
    make_application(name="blog", host="10.0.0.6")

    on_shop = mcp("list_applications", server="shop").data["results"]
    searched = mcp("list_applications", search="blo").data["results"]

    assert [row["name"] for row in on_shop] == ["shop"]
    assert on_shop[0]["server"]["name"] == "shop"
    assert [row["name"] for row in searched] == ["blog"]
    assert mcp("list_applications", server="nope").text == (
        "there is no server named 'nope'."
    )


@pytest.mark.django_db
def test_changes_that_need_the_account_password_are_handed_back(mcp, make_application):
    application = make_application()
    settled(application.server)
    settled(application)
    ApplicationRepository().update(
        application, last_check_status=Application.CheckStatus.OK
    )

    moved = mcp("update_server", server="web-1", host="10.0.0.9")
    renamed = mcp("update_server", server="web-1", name="web-2")
    guarded = mcp(
        "update_application", application="web-1", python_path="/usr/bin/python3"
    )
    retitled = mcp("update_application", application="web-1", name="shop")
    archive = mcp(
        "add_plan", application="shop", name="media", kind="archive", paths=["/srv"]
    )

    assert not moved.ok and moved.text == NEEDS_PASSWORD
    assert renamed.ok and renamed.data["name"] == "web-2"
    assert not guarded.ok and guarded.text == NEEDS_PASSWORD
    assert retitled.ok and retitled.data["name"] == "shop"
    assert not archive.ok and archive.text == NEEDS_PASSWORD
    assert not BackupPlan.objects.exists()
    application.refresh_from_db()
    assert application.python_path == PYTHON
    assert ServerRepository().active().get().host == "10.0.0.5"


@RUNS_JOBS
def test_take_backups_waits_and_reports_a_busy_application(
    mcp, admin, host, make_application
):
    make_application(name="shop", host="10.0.0.5")
    blog = make_application(name="blog", host="10.0.0.6")
    TakeLock().acquire(blog.pk, uuid4())

    taken = mcp("take_backups", all=True).data["results"]

    assert [(item["application"], item["ok"]) for item in taken] == [
        ("blog", False),
        ("shop", True),
    ]
    assert len(host.takes) == 1 and BackupFile.objects.count() == 1
    assert (
        mcp("take_backups").text
        == "name at least one application, or choose all of them."
    )


@RUNS_JOBS
def test_restores_are_always_rehearsals(mcp, admin, host, make_application):
    make_application(name="shop")
    make_application(name="blog", host="10.0.0.6")
    mcp("take_backups", applications=["shop"])
    backup = mcp("list_backups", application="shop").data["results"][0]

    rehearsed = mcp("rehearse_restore", backup=backup["id"], mode="replace")
    elsewhere = mcp(
        "rehearse_restore",
        backup=backup["id"],
        mode="merge",
        target_application="blog",
    )

    assert backup["application_name"] == "shop"
    assert rehearsed.ok and rehearsed.data["ok"], rehearsed.raw
    assert elsewhere.ok and elsewhere.data["ok"], elsewhere.raw
    assert [restore.dry_run for restore in host.restores] == [True, True]


@RUNS_JOBS
def test_plans_and_backups_through_tools(mcp, admin, host, make_application, tmp_path):
    make_application(name="shop")
    plan = mcp(
        "add_plan",
        application="shop",
        name="nightly",
        kind="dbs",
        interval_minutes=1440,
    )
    assert plan.ok, plan.text
    assert plan.data["keep"] == 5
    assert mcp("update_plan", plan=plan.data["id"], interval_minutes=60).ok
    assert mcp("run_plan", plan=plan.data["id"]).data["ok"]
    [listed_plan] = mcp("list_plans", application="shop").data["results"]
    assert listed_plan["application_name"] == "shop"

    backup = mcp("list_backups").data["results"][0]
    assert mcp("verify_backup", backup=backup["id"]).data["ok"]
    saved = mcp("download_backup", backup=backup["id"], path=str(tmp_path))
    assert saved.ok and (tmp_path / backup["name"]).exists()
    assert (
        "already exists"
        in mcp("download_backup", backup=backup["id"], path=str(tmp_path)).text
    )
    assert (
        "absolute" in mcp("download_backup", backup=backup["id"], path="here.dbs").text
    )
    actions = [
        entry["action"] for entry in mcp("list_activity", limit=50).data["results"]
    ]
    assert {"plan.create", "plan.update", "backup.run", "backup.verify"} <= set(actions)
    assert actions.count("backup.download") == 1
    by_application = mcp("list_activity", application="shop", limit=50).data["results"]
    assert {entry["application_name"] for entry in by_application} == {"shop"}


@pytest.mark.django_db
def test_env_tools_show_key_names_never_values(
    mcp, make_application, local_host, tmp_path
):
    env = tmp_path.resolve() / ".env"
    env.write_bytes(ENV)
    make_application(env_path=str(env))

    pulled = mcp("pull_env", application="web-1")
    listed = mcp("list_env_versions", application="web-1")

    assert pulled.ok, pulled.text
    assert pulled.data["version"]["keys"] == ["SECRET_KEY", "DEBUG"]
    assert "sk_live_very_secret" not in pulled.raw + listed.raw
    assert EnvVersion.objects.count() == 1


@pytest.mark.django_db
def test_capture_passphrase_never_returns_it(mcp, make_application, monkeypatch):
    make_application()
    found = ready_remote()
    found.answers[(PYTHON, "manage.py", "dbs_key", "--show")] = Result(
        0, "captured-secret\n"
    )
    monkeypatch.setattr(CONNECT, connecting_to(found))

    captured = mcp("capture_passphrase", application="web-1")

    assert captured.ok and captured.data == {"captured": True}
    assert (
        "captured-secret" not in captured.raw and BACKUP_PASSPHRASE not in captured.raw
    )


@pytest.mark.django_db(transaction=True)
def test_redeploys_are_always_rehearsals(mcp, world):  # noqa: F811
    ran = mcp(
        "rehearse_redeploy",
        source_application="web-1",
        target_application="web-2",
        backup=str(world["backup"].pk),
    )

    assert ran.ok and ran.data["ok"], ran.raw
    assert [
        "--dry-run" in restore["argv"] for restore in world["sent"]["restores"]
    ] == [True]
    assert world["sent"]["taken"] == []


@pytest.mark.django_db(transaction=True)
def test_putting_a_new_application_back_is_only_ever_rehearsed(mcp, api, world):  # noqa: F811
    failing_migration(world)
    response = api.post("/api/redeploy/", for_real(world), format="json")
    moved = response.json()["activity"]
    pushed = world["env"].read_bytes()

    ran = mcp("rehearse_revert", move=moved)

    assert ran.ok and ran.data["ok"], ran.raw
    [revert] = world["sent"]["restores"]
    assert "--dry-run" in revert["argv"] and "--flush" in revert["argv"]
    assert world["env"].read_bytes() == pushed


@pytest.mark.django_db
def test_unknown_references_are_named(mcp, admin):
    assert mcp("get_server", server="nope").text == "there is no server named 'nope'."
    assert (
        mcp("get_application", application="nope").text
        == "there is no application named 'nope'."
    )
    assert mcp("get_plan", plan="nope").text == "'nope' is not a plan id."


@pytest.mark.django_db
def test_a_compose_application_is_added_with_its_service(
    mcp, admin, make_server, monkeypatch
):
    from tests.manager.terminal.test_compose_applications import (
        FOLDER,
        SERVICE,
        ComposeProject,
    )

    monkeypatch.setattr(CONNECT, connecting_to(ComposeProject()))
    make_server()

    found = mcp("discover_applications", server="web-1", folder=FOLDER)
    added = mcp("add_application", server="web-1", folder=FOLDER, name="shop")

    assert found.ok, found.text
    assert [candidate["kind"] for candidate in found.data["candidates"]] == ["compose"]
    assert added.ok, added.text
    assert (
        added.data["kind"],
        added.data["engine"],
        added.data["compose_service"],
    ) == (
        "compose",
        "docker",
        SERVICE,
    )
    assert added.data["check"]["status"] == Application.CheckStatus.OK
