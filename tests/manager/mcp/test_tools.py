from datetime import timedelta
from uuid import uuid4

import pytest
from django.utils import timezone

from dbs.manager.backups.locks import TakeLock
from dbs.manager.backups.models import BackupFile, BackupPlan
from dbs.manager.envfiles.models import EnvVersion
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
    BACKUP_PASSPHRASE,
    PROJECT_DIR,
    PYTHON,
    SSH_PASSWORD,
    connecting_to,
    host_key_line,
    private_key_text,
)
from tests.manager.terminal.test_servers import ready_remote
from tests.manager.test_redeploy import world  # noqa: F401
from tests.manager.support import logged

CONNECT = "dbs.manager.servers.services.connection_service.connect"
FETCH_HOST_KEY = "dbs.manager.servers.services.server_service.fetch_host_key"
RUNS_JOBS = pytest.mark.django_db(transaction=True)
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
)
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
def test_no_tool_reveals_restores_for_real_removes_or_deletes(mcp):
    tools = tool_list(mcp)

    names = [tool["name"] for tool in tools]
    assert not [name for name in names if any(word in name for word in FORBIDDEN)]
    for tool in tools:
        properties = set(tool["inputSchema"]["properties"])
        assert not properties & {
            "account_password",
            "rehearse",
            "rehearsal",
            "real",
            "host_key",
        }
        if tool["name"] != "add_server":
            assert not properties & {"password", "key_passphrase"}


@pytest.mark.django_db
def test_reading_tools_return_what_the_api_returns(mcp, api, make_server):
    server = make_server()

    listed = mcp("list_servers").data["results"]
    shown = mcp("get_server", server="web-1").data

    assert listed == api.get("/api/servers/").json()["results"]
    assert shown == api.get(f"/api/servers/{server.pk}/").json()
    assert mcp("manager_overview").data == api.get("/api/dashboard/").json()


@pytest.mark.django_db
def test_adding_a_server_with_a_password_finds_its_project_and_checks_it(
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
        project_dir=PROJECT_DIR,
    )

    assert added.ok, added.text
    assert added.data["python_path"] == PYTHON
    assert added.data["check"]["status"] == Server.CheckStatus.OK
    assert SSH_PASSWORD not in added.raw
    server = ServerRepository().active().get()
    assert server.host_key == offered
    assert ServerConnectionService(admin).credentials(server).password == SSH_PASSWORD
    assert [entry.actor for entry in logged("server.create")] == [admin]


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
        discover=False,
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
def test_changes_that_need_the_account_password_are_handed_back(mcp, make_server):
    server = make_server()
    ServerRepository().update(
        server,
        created_at=timezone.now() - timedelta(hours=2),
        last_check_status=Server.CheckStatus.OK,
    )

    guarded = mcp("update_server", server="web-1", python_path="/usr/bin/python3")
    renamed = mcp("update_server", server="web-1", name="web-2")
    archive = mcp(
        "add_plan", server="web-2", name="media", kind="archive", paths=["/srv"]
    )

    assert not guarded.ok and guarded.text == NEEDS_PASSWORD
    assert renamed.ok and renamed.data["name"] == "web-2"
    assert not archive.ok and archive.text == NEEDS_PASSWORD
    assert not BackupPlan.objects.exists()


@RUNS_JOBS
def test_take_backups_waits_and_reports_a_busy_server(mcp, admin, host, make_server):
    make_server(name="shop", host="10.0.0.5")
    blog = make_server(name="blog", host="10.0.0.6")
    TakeLock().acquire(blog.pk, uuid4())

    taken = mcp("take_backups", all=True).data["results"]

    assert [(item["server"], item["ok"]) for item in taken] == [
        ("blog", False),
        ("shop", True),
    ]
    assert len(host.takes) == 1 and BackupFile.objects.count() == 1
    assert (
        mcp("take_backups").text == "name at least one server, or choose all of them."
    )


@RUNS_JOBS
def test_restores_are_always_rehearsals(mcp, admin, host, make_server):
    make_server(name="shop")
    mcp("take_backups", servers=["shop"])
    backup = mcp("list_backups", server="shop").data["results"][0]

    rehearsed = mcp("rehearse_restore", backup=backup["id"], mode="replace")

    assert rehearsed.ok and rehearsed.data["ok"], rehearsed.raw
    assert [restore.dry_run for restore in host.restores] == [True]


@RUNS_JOBS
def test_plans_and_backups_through_tools(mcp, admin, host, make_server, tmp_path):
    make_server(name="shop")
    plan = mcp(
        "add_plan", server="shop", name="nightly", kind="dbs", interval_minutes=1440
    )
    assert plan.ok, plan.text
    assert plan.data["keep"] == 5
    assert mcp("update_plan", plan=plan.data["id"], interval_minutes=60).ok
    assert mcp("run_plan", plan=plan.data["id"]).data["ok"]

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


@pytest.mark.django_db
def test_env_tools_show_key_names_never_values(mcp, make_server, local_host, tmp_path):
    env = tmp_path.resolve() / ".env"
    env.write_bytes(ENV)
    make_server(env_path=str(env))

    pulled = mcp("pull_env", server="web-1")
    listed = mcp("list_env_versions", server="web-1")

    assert pulled.ok, pulled.text
    assert pulled.data["version"]["keys"] == ["SECRET_KEY", "DEBUG"]
    assert "sk_live_very_secret" not in pulled.raw + listed.raw
    assert EnvVersion.objects.count() == 1


@pytest.mark.django_db
def test_capture_passphrase_never_returns_it(mcp, make_server, monkeypatch):
    make_server()
    remote = ready_remote()
    remote.answers[(PYTHON, "manage.py", "dbs_key", "--show")] = type(
        "R", (), {"ok": True, "stdout": "captured-secret\n", "stderr": ""}
    )()
    monkeypatch.setattr(CONNECT, connecting_to(remote))

    captured = mcp("capture_passphrase", server="web-1")

    assert captured.ok and captured.data == {"captured": True}
    assert (
        "captured-secret" not in captured.raw and BACKUP_PASSPHRASE not in captured.raw
    )


@pytest.mark.django_db(transaction=True)
def test_redeploys_are_always_rehearsals(mcp, world):  # noqa: F811
    ran = mcp(
        "rehearse_redeploy",
        source_server="web-1",
        target_server="web-2",
        backup=str(world["backup"].pk),
    )

    assert ran.ok and ran.data["ok"], ran.raw
    assert [
        "--dry-run" in restore["argv"] for restore in world["sent"]["restores"]
    ] == [True]


@pytest.mark.django_db
def test_unknown_references_are_named(mcp, admin):
    assert mcp("get_server", server="nope").text == "there is no server named 'nope'."
    assert mcp("get_plan", plan="nope").text == "'nope' is not a plan id."


@pytest.mark.django_db
def test_a_compose_server_is_added_with_its_service(
    mcp, admin, offered, monkeypatch, tmp_path
):
    from tests.manager.servers.compose import ComposeHost, connected_to

    backups = tmp_path / "host" / "backups"
    backups.mkdir(parents=True)
    connected_to(monkeypatch, ComposeHost(tmp_path / "container"))
    confirmation = confirmed(mcp, admin, host="10.0.0.7")

    added = mcp(
        "add_server",
        name="shop",
        host="10.0.0.7",
        username="deploy",
        confirmation=confirmation,
        auth_method="password",
        password=SSH_PASSWORD,
        runtime="compose",
        compose_service="backend",
        compose_files=["compose.yaml"],
        project_dir="/srv/shop",
        python_path="python",
        remote_backup_dir=str(backups),
    )

    assert added.ok, added.text
    assert (added.data["runtime"], added.data["compose_service"]) == (
        "compose",
        "backend",
    )
    assert added.data["check"]["status"] == Server.CheckStatus.OK
    assert SSH_PASSWORD not in added.raw
