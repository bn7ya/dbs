import json
import subprocess
import sys

from tests.manager.test_cli import ROOT, clean_env

PASSWORD = "correct-horse-battery-staple"
TIMEOUT = 120


def manager(home, *args, stdin=""):
    return subprocess.run(
        [sys.executable, "-m", "dbs.manager", *args, "--data-dir", str(home)],
        cwd=ROOT,
        env=clean_env(),
        input=stdin,
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
    )


def line(identifier, method, **params):
    return json.dumps(
        {"jsonrpc": "2.0", "id": identifier, "method": method, "params": params}
    )


def test_django_dbs_mcp_speaks_json_rpc_on_stdout_alone(tmp_path):
    home = tmp_path / "home"
    assert (
        manager(
            home, "createuser", "sara", "--password-stdin", stdin=PASSWORD
        ).returncode
        == 0
    )
    session = "\n".join(
        [
            line(1, "initialize", protocolVersion="2025-06-18", capabilities={}),
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
            line(2, "tools/list"),
            line(3, "tools/call", name="list_servers", arguments={}),
            line(4, "tools/call", name="get_server", arguments={"server": "nope"}),
        ]
    )

    ran = manager(home, "mcp", stdin=session + "\n")

    assert ran.returncode == 0, ran.stderr
    replies = [json.loads(text) for text in ran.stdout.splitlines()]
    assert [reply["id"] for reply in replies] == [1, 2, 3, 4]
    assert replies[0]["result"]["serverInfo"]["name"] == "django-dbs"
    assert "take_backups" in {tool["name"] for tool in replies[1]["result"]["tools"]}
    assert replies[2]["result"]["structuredContent"] == {"results": []}
    assert replies[3]["result"]["isError"] is True


def test_django_dbs_mcp_needs_an_account(tmp_path):
    ran = manager(tmp_path / "home", "mcp", stdin="")

    assert ran.returncode == 1
    assert ran.stdout == ""
    assert "createuser" in ran.stderr
