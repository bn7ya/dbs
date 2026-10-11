import io
import json

from dbs.manager.mcp.protocol import (
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    PROTOCOL_VERSIONS,
    UNEXPECTED,
    Server,
    Tool,
    ToolFailed,
)


class Refused(Exception):
    pass


def echo(arguments):
    print("a stray print")
    return {"said": arguments["words"]}


def broken(arguments):
    raise RuntimeError("boom")


def refusing(arguments):
    raise Refused("not today")


def failing(arguments):
    raise ToolFailed("try another way")


def server():
    tools = [
        Tool(
            "echo",
            "Echo",
            "Says it back.",
            {"words": {"type": "string"}},
            echo,
            ("words",),
            True,
        ),
        Tool("broken", "Broken", "Always breaks.", {}, broken),
        Tool("refusing", "Refusing", "Always refuses.", {}, refusing),
        Tool("failing", "Failing", "Always fails.", {}, failing),
    ]
    return Server(
        tools,
        name="test",
        version="1.0",
        instructions="Be kind.",
        describe=lambda exc: str(exc) if isinstance(exc, Refused) else None,
    )


def exchange(*messages):
    reading = io.StringIO(
        "".join((m if isinstance(m, str) else json.dumps(m)) + "\n" for m in messages)
    )
    writing = io.StringIO()
    server().serve(reading, writing)
    return [json.loads(line) for line in writing.getvalue().splitlines()]


def request(identifier, method, **params):
    return {"jsonrpc": "2.0", "id": identifier, "method": method, "params": params}


def call(identifier, name, **arguments):
    return request(identifier, "tools/call", name=name, arguments=arguments)


def test_initialize_agrees_on_a_version_and_names_the_server():
    [known, unknown] = exchange(
        request(1, "initialize", protocolVersion="2025-03-26"),
        request(2, "initialize", protocolVersion="1999-01-01"),
    )

    assert known["result"]["protocolVersion"] == "2025-03-26"
    assert unknown["result"]["protocolVersion"] == PROTOCOL_VERSIONS[0]
    assert known["result"]["serverInfo"] == {"name": "test", "version": "1.0"}
    assert known["result"]["capabilities"] == {"tools": {"listChanged": False}}
    assert known["result"]["instructions"] == "Be kind."


def test_notifications_get_no_reply_and_ping_answers():
    replies = exchange(
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        request(7, "ping"),
    )

    assert replies == [{"jsonrpc": "2.0", "id": 7, "result": {}}]


def test_tools_list_describes_each_tool_with_a_closed_schema():
    [listed] = exchange(request(1, "tools/list"))

    echo_tool = listed["result"]["tools"][0]
    assert echo_tool["name"] == "echo"
    assert echo_tool["inputSchema"] == {
        "type": "object",
        "properties": {"words": {"type": "string"}},
        "required": ["words"],
        "additionalProperties": False,
    }
    assert echo_tool["annotations"]["readOnlyHint"] is True
    assert echo_tool["annotations"]["destructiveHint"] is False


def test_a_call_returns_text_and_structured_content_and_keeps_stdout_clean(capsys):
    [answer] = exchange(call(1, "echo", words="hello"))

    result = answer["result"]
    assert result["isError"] is False
    assert result["structuredContent"] == {"said": "hello"}
    assert json.loads(result["content"][0]["text"]) == {"said": "hello"}
    assert "a stray print" in capsys.readouterr().err


def test_tool_failures_are_results_not_protocol_errors():
    replies = exchange(
        call(1, "refusing"),
        call(2, "failing"),
        call(3, "broken"),
        call(4, "echo"),
        call(5, "echo", words="hi", extra=1),
        call(6, "echo", words="still here"),
    )

    texts = [reply["result"]["content"][0]["text"] for reply in replies[:5]]
    assert all(reply["result"]["isError"] for reply in replies[:5])
    assert texts[0] == "not today" and texts[1] == "try another way"
    assert texts[2] == UNEXPECTED
    assert "needs words" in texts[3] and "takes no extra" in texts[4]
    assert replies[5]["result"]["structuredContent"] == {"said": "still here"}


def test_protocol_errors_name_what_was_wrong():
    replies = exchange(
        "{not json",
        request(2, "resources/list"),
        request(3, "tools/call", name="nope"),
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": [1]},
        {"id": 5, "method": "ping"},
        [request(6, "ping")],
    )

    codes = [reply["error"]["code"] for reply in replies]
    assert codes == [
        PARSE_ERROR,
        METHOD_NOT_FOUND,
        INVALID_PARAMS,
        INVALID_PARAMS,
        INVALID_REQUEST,
        INVALID_REQUEST,
    ]
