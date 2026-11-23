"""Stdio MCP entry point for the fixed P3 tracer tools."""
from __future__ import annotations

import argparse
import asyncio
import functools
import json
from pathlib import Path, PurePosixPath

import yaml
from jsonschema import Draft202012Validator
from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from .digest import digest
from . import protocol
from .policy.session import GuardedSession
from .sandbox.backend import RunSpec, SessionConfig
from .sandbox.runner import BwrapBackend

HANDLERS = {"fs.find", "fs.read", "fs.edit"}
TYPES = {"path": "string", "string": "string", "enum": "string", "int": "integer", "bool": "boolean"}
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


# --- interface v1: run + the five reviewed typed tools, guarded exactly like the tracer --------

_RUN_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["command"],
               "properties": {"command": {"type": "string", "minLength": 1, "maxLength": protocol.MAX_ACTION_CHARS}}}


def _v1_tool_schema(spec: "protocol.ToolSpec") -> dict:
    properties, required = {}, []
    for argument, arg in spec.args.items():
        schema = {"type": TYPES[arg.type]}
        if arg.type == "enum":
            schema["enum"] = list(arg.values)
        if arg.minimum is not None:
            schema["minimum"] = arg.minimum
        if arg.maximum is not None:
            schema["maximum"] = arg.maximum
        if arg.min_length is not None:
            schema["minLength"] = arg.min_length
        if arg.max_length is not None:
            schema["maxLength"] = arg.max_length
        if arg.default is not None:
            schema["default"] = arg.default
        if arg.type == "path":
            schema["minLength"] = 1
            schema["maxLength"] = 4096
        properties[argument] = schema
        if arg.required:
            required.append(argument)
    schema = {"type": "object", "properties": properties, "required": required, "additionalProperties": False}
    Draft202012Validator.check_schema(schema)
    return schema


def build_v1_tools() -> dict[str, types.Tool]:
    """`run` plus interface v1's reviewed typed tools (protocol.load_tools), as MCP tools.

    Never includes an apply, approve or commit tool: this server has no approval authority.
    """
    tools = {"run": types.Tool(name="run", description="Run one shell command or short script.",
                                inputSchema=_RUN_SCHEMA)}
    for name, spec in protocol.load_tools().items():
        tools[name] = types.Tool(name=name, description=spec.description, inputSchema=_v1_tool_schema(spec))
    return tools


@functools.lru_cache(maxsize=1)
def _v1_arg_types() -> dict:
    return {name: {arg: spec.type for arg, spec in tool.args.items()}
            for name, tool in protocol.load_tools().items()}


def audit_args(name: str, arguments: dict) -> list:
    """A typed call as recorded for human review: paths, numbers, flags and enum choices as
    given, free-text literals (edit contents, patterns, globs) only by length, so the audit log
    shows what ran without keeping file contents. A list of [name, value] pairs in the tool's
    interface order, because the audit log is written with sorted keys."""
    types_ = _v1_arg_types().get(name, {})
    order = list(types_) + sorted(set(arguments) - set(types_))
    return [[key, arguments[key] if types_.get(key) in ("path", "int", "bool", "enum")
             else f"<{len(str(arguments[key]))} chars>"] for key in order if key in arguments]


class InterfaceV1:
    """Serves `run` plus the typed tools from protocol.load_tools() through one GuardedSession.

    No apply/approve/commit tool is registered here: policy outcomes (ok/pending/rejected) and
    file changes are reported back to the model as an observation; a human acts on `lilguy
    approve` separately, exactly as for the tracer.
    """

    def __init__(self, tools, open_guarded, interface=protocol.INTERFACE_VERSION):
        self.tools = tools
        self.open_guarded = open_guarded
        self.guarded = None
        self.interface = interface
        self.program = Path(__file__).with_name("_typed_step.py").read_text(encoding="utf8")

    def _run_spec(self, name, arguments) -> RunSpec | None:
        if name == "run":
            command = arguments.get("command", "")
            if not isinstance(command, str) or not command.strip():
                return None
            return RunSpec(shell=command)
        values = {key: spec["default"] for key, spec in self.tools[name].inputSchema["properties"].items()
                  if "default" in spec}
        values.update(arguments)
        path = values.get("path")
        if path is not None:
            posix = PurePosixPath(path)
            if posix.is_absolute() or ".." in posix.parts or "\0" in path:
                return None
        if any(type(values[key]) is not int for key, spec in self.tools[name].inputSchema["properties"].items()
               if spec["type"] == "integer" and key in values):
            return None
        return RunSpec(argv=["/usr/bin/python3", "-I", "-c", self.program, name, "--", json.dumps(values),
                             str(self.interface)])

    def call(self, name, arguments) -> types.CallToolResult:
        tool = self.tools.get(name)
        if tool is None or not Draft202012Validator(tool.inputSchema).is_valid(arguments):
            return _reply("Invalid tool or arguments", error=True)
        spec = self._run_spec(name, arguments)
        if spec is None:
            return _reply("Invalid tool or arguments", error=True)
        typed_tool = None if name == "run" else name
        try:
            if self.guarded is None:
                self.guarded = self.open_guarded()
            if typed_tool is None:
                outcome = self.guarded.run(spec, typed_tool=None)
            else:
                outcome = self.guarded.run(spec, typed_tool=typed_tool,
                                           tool_args=audit_args(typed_tool, arguments))
        except (OSError, RuntimeError, ValueError):
            return _reply("Unable to execute the sandboxed step", error=True)
        result = outcome.result
        policy = {"ok": "ok", "pending": "pending", "reject": "rejected"}.get(outcome.decision.kind)
        if policy is None:
            return _reply("Unrecognized sandbox policy decision", error=True)
        changes = [(entry.op, entry.path) for entry in result.step_diff]
        text = protocol.render_observation(
            exit_code=result.exit_code, stdout=result.stdout, stderr=result.stderr,
            tags=result.tags, changes=changes, policy=policy, reason=outcome.decision.detail,
            version=self.interface,
        )
        return _reply(text, error=(policy != "ok") or result.exit_code != 0)


async def serve_v1(server_impl: InterfaceV1) -> None:
    server = Server("lilguy-interface-v1")

    @server.list_tools()
    async def list_tools():
        return list(server_impl.tools.values())

    @server.call_tool(validate_input=False)
    async def call_tool(name, arguments):
        return server_impl.call(name, arguments)

    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--toolset", required=True, type=Path, help="Trusted toolset.yaml outside the workspace")
    parser.add_argument("--interface-v1", action="store_true",
                         help="Serve interface v1 (run + typed tools) instead of the pilot tracer's three tools")
    parser.add_argument("--interface", type=int, default=protocol.INTERFACE_VERSION,
                        choices=protocol.SUPPORTED_VERSIONS,
                        help="interface version of the observations (default: the shipped model's)")
    parser.add_argument("--read-only", action="store_true",
                        help="Question mode (interface v3 `ask`): the policy rejects and rolls back any change")
    args = parser.parse_args(argv)
    workspace = args.workspace.resolve()
    state = args.state_dir.resolve()
    source = args.toolset.resolve()
    if source.is_relative_to(workspace) or source.is_relative_to(state):
        parser.error("The trusted toolset must be outside the workspace and session state")
    return args


def trusted_policies(*, read_only: bool):
    """The caller-side policies for a session: None keeps the defaults; question mode refuses
    every change (the defaults' other rules still apply inside Policy(read_only=True))."""
    from .policy.engine import Policy
    return [Policy(read_only=True)] if read_only else None


def main(argv=None) -> None:
    args = _parse_args(argv)
    workspace = args.workspace.resolve()
    state = args.state_dir.resolve()
    source = args.toolset.resolve()

    def open_guarded():
        backend = BwrapBackend()
        session = backend.open_session(workspace, SessionConfig(state_dir=state, network="off"))
        return GuardedSession(backend, session, trusted_policies(read_only=args.read_only))

    if args.interface_v1:
        asyncio.run(serve_v1(InterfaceV1(build_v1_tools(), open_guarded, args.interface)))
    else:
        asyncio.run(serve(Tracer(load_tools(source), open_guarded)))


if __name__ == "__main__":
    main()
