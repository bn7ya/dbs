import json

import pytest

from dbs.manager.mcp.server import build
from tests.manager.terminal.conftest import (  # noqa: F401
    local_host,
    make_application,
    make_server,
    storage,
)


class Called:
    def __init__(self, result):
        self.result = result

    @property
    def ok(self):
        return not self.result["isError"]

    @property
    def data(self):
        return self.result.get("structuredContent")

    @property
    def text(self):
        return self.result["content"][0]["text"]

    @property
    def raw(self):
        return json.dumps(self.result)


@pytest.fixture
def mcp(admin, settings):
    settings.DBS_MANAGER_JOBS_INLINE = True
    server = build(admin)
    counter = iter(range(1, 10_000))

    def call(tool, **arguments):
        reply = server.handle(
            {
                "jsonrpc": "2.0",
                "id": next(counter),
                "method": "tools/call",
                "params": {"name": tool, "arguments": arguments},
            }
        )
        return Called(reply["result"])

    call.server = server
    return call
