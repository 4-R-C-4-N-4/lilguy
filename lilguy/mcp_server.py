"""Stdio MCP entry point for the fixed P3 tracer tools."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path, PurePosixPath

import yaml
from jsonschema import Draft202012Validator
from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from .digest import digest
from .policy.session import GuardedSession
from .sandbox.backend import RunSpec, SessionConfig
from .sandbox.runner import BwrapBackend

HANDLERS = {"fs.find", "fs.read", "fs.edit"}
TYPES = {"path": "string", "string": "string", "enum": "string", "int": "integer"}
SCHEMA_KEYS = {"min": "minimum", "max": "maximum", "values": "enum",
               "min_length": "minLength", "max_length": "maxLength", "default": "default"}


def load_tools(toolset: Path) -> dict[str, types.Tool]:
    """Load schemas from an operator-supplied toolset outside the workspace."""
    tools = {}
    for name, definition in yaml.safe_load(toolset.read_text(encoding="utf8"))["tools"].items():
        if not definition.get("tracer"):
            continue
        if name not in HANDLERS:
            raise ValueError("unknown tracer tool")
        properties = {}
        required = []
        for argument, spec in definition["args"].items():
            schema = {"type": TYPES[spec["type"]]}
            schema.update({target: spec[key] for key, target in SCHEMA_KEYS.items() if key in spec})
            if spec["type"] == "path":
                schema["minLength"] = 1
                schema["maxLength"] = 4096
            properties[argument] = schema
            if "default" not in spec and not spec.get("optional"):
                required.append(argument)
        schema = {"type": "object", "properties": properties, "required": required,
                  "additionalProperties": False}
        description = definition.get("description")
        Draft202012Validator.check_schema(schema)
        tools[name] = types.Tool(name=name, description=description, inputSchema=schema)
    if tools.keys() != HANDLERS:
        raise ValueError("incomplete tracer toolset")
    return tools


def _reply(message: str, error: bool = False) -> types.CallToolResult:
    return types.CallToolResult(isError=error, content=[types.TextContent(type="text", text=message)])


class Tracer:
    def __init__(self, tools, open_guarded):
        self.tools = tools
        self.open_guarded = open_guarded
        self.guarded = None
        self.program = Path(__file__).with_name("_typed_step.py").read_text(encoding="utf8")

    def call(self, name, arguments):
        tool = self.tools.get(name)
        if tool is None or not Draft202012Validator(tool.inputSchema).is_valid(arguments):
            return _reply("Invalid tracer tool or arguments", error=True)
        values = {key: spec["default"] for key, spec in tool.inputSchema["properties"].items()
                  if "default" in spec}
        values.update(arguments)
        path = PurePosixPath(values["path"])
        if path.is_absolute() or ".." in path.parts or "\0" in values["path"]:
            return _reply("Expected a workspace-relative path", error=True)
        if any(type(values[key]) is not int for key, spec in tool.inputSchema["properties"].items()
               if spec["type"] == "integer" and key in values):
            return _reply("Expected integer arguments", error=True)

        # The fixed program receives arguments as data after the option boundary.
        spec = RunSpec(argv=["/usr/bin/python3", "-I", "-c", self.program, name, "--", json.dumps(values)])
        try:
            if self.guarded is None:
                self.guarded = self.open_guarded()
            outcome = self.guarded.run(spec, typed_tool=name)
        except (OSError, RuntimeError, ValueError):
            return _reply("Unable to execute the sandboxed step", error=True)
        result = outcome.result
        if outcome.decision.kind != "ok":
            return _reply(f"Policy decision: {outcome.decision.kind}", error=True)
        observation = digest(result.exit_code, result.stdout, result.stderr, result.tags)
        return _reply(observation.text, error=result.exit_code != 0)


async def serve(tracer: Tracer) -> None:
    server = Server("lilguy-p3")

    @server.list_tools()
    async def list_tools():
        return list(tracer.tools.values())

    @server.call_tool(validate_input=False)
    async def call_tool(name, arguments):
        return tracer.call(name, arguments)

    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--toolset", required=True, type=Path, help="Trusted toolset.yaml outside the workspace")
    args = parser.parse_args(argv)
    workspace = args.workspace.resolve()
    state = args.state_dir.resolve()
    source = args.toolset.resolve()
    if source.is_relative_to(workspace) or source.is_relative_to(state):
        parser.error("The trusted toolset must be outside the workspace and session state")

    def open_guarded():
        backend = BwrapBackend()
        session = backend.open_session(workspace, SessionConfig(state_dir=state, network="off"))
        return GuardedSession(backend, session)

    asyncio.run(serve(Tracer(load_tools(source), open_guarded)))


if __name__ == "__main__":
    main()
