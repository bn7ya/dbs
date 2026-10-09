import shlex
from contextlib import contextmanager

from dbs.manager.servers.gateways import RemoteHost
from dbs.transports import RemoteResult
from tests.manager.servers.support import LocalSftpSession

CONNECT = "dbs.manager.servers.services.connection_service.connect"


def argv_of(script):
    body = shlex.split(script)[2]
    lines = body.splitlines()
    return shlex.split(lines[-1][len("exec ") :]), lines[:-1]


class ScriptedSession(LocalSftpSession):
    def __init__(self, host, commands):
        super().__init__()
        self.host = host
        self.commands = commands
        self.runs = []

    def run(self, script, stdin_line=None, timeout=None):
        argv, setup = argv_of(script)
        self.runs.append({"argv": argv, "setup": setup, "stdin": stdin_line})
        answer = self.commands.get(tuple(argv))
        if answer is None:
            for prefix, handler in self.commands.items():
                if callable(handler) and tuple(argv[: len(prefix)]) == prefix:
                    answer = handler
                    break
        if answer is None:
            return RemoteResult(127, "", f"{argv[0]}: not found")
        if callable(answer):
            answer = answer(argv, stdin_line)
        return RemoteResult(*answer)


class Hosts:
    def __init__(self):
        self.commands = {}
        self.sessions = []

    def answer(self, host, argv, result):
        self.commands.setdefault(host, {})[tuple(argv)] = result

    def runs(self, host):
        return [run for s in self.sessions if s.host == host for run in s.runs]


def scripted_hosts(monkeypatch):
    hosts = Hosts()

    @contextmanager
    def connect(credentials):
        session = ScriptedSession(
            credentials.host, hosts.commands.get(credentials.host, {})
        )
        hosts.sessions.append(session)
        try:
            yield RemoteHost(session)
        finally:
            session.close()

    monkeypatch.setattr(CONNECT, connect)
    return hosts
