from __future__ import annotations

import contextlib
import json
import logging
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import IO, Any, Optional

JSONRPC = "2.0"
PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
UNEXPECTED = (
    "The tool failed unexpectedly; the manager's log on stderr has the details."
)

logger = logging.getLogger("dbs.manager.mcp")

Handler = Callable[[Mapping[str, Any]], Mapping[str, Any]]
Describe = Callable[[BaseException], Optional[str]]


class ToolFailed(Exception):
    pass


@dataclass(frozen=True)
class Tool:
    name: str
    title: str
    description: str
    properties: Mapping[str, Any]
    handler: Handler
    required: Sequence[str] = ()
    read_only: bool = False
    idempotent: bool = False

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": dict(self.properties),
            "required": list(self.required),
            "additionalProperties": False,
        }

    def listed(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "inputSchema": self.input_schema,
            "annotations": {
                "title": self.title,
                "readOnlyHint": self.read_only,
                "destructiveHint": False,
                "idempotentHint": self.read_only or self.idempotent,
            },
        }

    def checked(self, arguments: Mapping[str, Any]) -> None:
        unknown = sorted(set(arguments) - set(self.properties))
        if unknown:
            raise ToolFailed(f"{self.name} takes no {', '.join(unknown)}.")
        missing = [name for name in self.required if arguments.get(name) in (None, "")]
        if missing:
            raise ToolFailed(f"{self.name} needs {', '.join(missing)}.")


class Server:
    def __init__(
        self,
        tools: Sequence[Tool],
        *,
        name: str,
        version: str,
        instructions: str,
        describe: Describe,
    ) -> None:
        self.tools = {tool.name: tool for tool in tools}
        self.name = name
        self.version = version
        self.instructions = instructions
        self.describe = describe

    def serve(self, reading: IO[str], writing: IO[str]) -> None:
        for line in reading:
            if not line.strip():
                continue
            try:
                message = json.loads(line)
            except ValueError:
                reply: dict[str, Any] | None = _error(None, PARSE_ERROR, "Parse error")
            else:
                reply = self.handle(message)
            if reply is not None:
                writing.write(json.dumps(reply, ensure_ascii=False, default=str) + "\n")
                writing.flush()

    def handle(self, message: Any) -> dict[str, Any] | None:
        if not isinstance(message, dict):
            return _error(None, INVALID_REQUEST, "Invalid request")
        known = "id" in message
        method = message.get("method")
        if message.get("jsonrpc") != JSONRPC or not isinstance(method, str):
            return (
                _error(message.get("id"), INVALID_REQUEST, "Invalid request")
                if known
                else None
            )
        if not known:
            return None
        params = message.get("params") or {}
        if not isinstance(params, dict):
            return _error(message["id"], INVALID_PARAMS, "params must be an object")
        answer = self._answer(method, params)
        if isinstance(answer, _Failure):
            return _error(message["id"], answer.code, answer.message)
        return {"jsonrpc": JSONRPC, "id": message["id"], "result": answer}

    def _answer(self, method: str, params: Mapping[str, Any]) -> Any:
        if method == "initialize":
            return self._initialized(params)
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": [tool.listed() for tool in self.tools.values()]}
        if method == "tools/call":
            return self._called(params)
        return _Failure(METHOD_NOT_FOUND, f"Method not found: {method}")

    def _initialized(self, params: Mapping[str, Any]) -> dict[str, Any]:
        asked = params.get("protocolVersion")
        return {
            "protocolVersion": asked
            if asked in PROTOCOL_VERSIONS
            else PROTOCOL_VERSIONS[0],
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": self.name, "version": self.version},
            "instructions": self.instructions,
        }

    def _called(self, params: Mapping[str, Any]) -> Any:
        tool = self.tools.get(params.get("name", ""))
        if tool is None:
            return _Failure(INVALID_PARAMS, f"Unknown tool: {params.get('name')}")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return _Failure(INVALID_PARAMS, "arguments must be an object")
        try:
            tool.checked(arguments)
            with contextlib.redirect_stdout(sys.stderr):
                data = dict(tool.handler(arguments))
        except ToolFailed as exc:
            return _failed(str(exc))
        except Exception as exc:
            described = self.describe(exc)
            if described is None:
                logger.exception("tool %s failed", tool.name)
                return _failed(UNEXPECTED)
            return _failed(described)
        text = json.dumps(data, ensure_ascii=False, default=str)
        return {
            "content": [{"type": "text", "text": text}],
            "structuredContent": json.loads(text),
            "isError": False,
        }


@dataclass(frozen=True)
class _Failure:
    code: int
    message: str


def _failed(message: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": message}], "isError": True}


def _error(identifier: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": JSONRPC,
        "id": identifier,
        "error": {"code": code, "message": message},
    }
