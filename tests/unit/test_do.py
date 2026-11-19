"""Unit tests for `lilguy do`'s own safety logic: no sandbox, no network, no model.

Covers what do.py owns on top of the shared loop/protocol: the preflight fail-safes, the
call_tool wrapper's refusal to trust an unparseable policy status, the versioned private
record, ground-truth session lookup, and CLI dispatch/argument wiring. The live, guarded
end-to-end drive (real sandbox, stubbed-at-the-socket-boundary model) is exercised in
tests/sandbox/test_do_live.py.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from lilguy import cli, do, loop, protocol as p


# --- preflight: sandbox and model ------------------------------------------------------------

def test_check_sandbox_raises_do_safety_error_on_required_failure(monkeypatch):
    from lilguy.probe import CheckResult
    monkeypatch.setattr(do, "run_probe", None, raising=False)
    monkeypatch.setattr("lilguy.probe.run_probe",
                        lambda: [CheckResult("bwrap_version", True, "fail", "bwrap not found")])
    with pytest.raises(do.DoSafetyError, match="sandbox is not available"):
        do.check_sandbox()


def test_check_sandbox_passes_when_only_optional_checks_fail(monkeypatch):
    from lilguy.probe import CheckResult
    monkeypatch.setattr("lilguy.probe.run_probe",
                        lambda: [CheckResult("cgroup_delegation", False, "warn", "falling back")])
    do.check_sandbox()  # must not raise


def test_check_model_raises_do_safety_error_when_unreachable(monkeypatch):
    import urllib.error

    def boom(*a, **k):
        raise urllib.error.URLError("connection refused")
    monkeypatch.setattr("urllib.request.urlopen", boom)
    with pytest.raises(do.DoSafetyError, match="not reachable"):
        do.check_model("http://127.0.0.1:8080")


def test_check_model_passes_when_reachable(monkeypatch):
    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: _Resp())
    do.check_model("http://127.0.0.1:8080")  # must not raise


# --- call_tool: never trust an error with no parseable policy line --------------------------

class _FakeResult:
    def __init__(self, text, is_error):
        from types import SimpleNamespace
        self.content = [SimpleNamespace(text=text)]
        self.isError = is_error


class _FakeClient:
    def __init__(self, text, is_error):
        self._text, self._is_error = text, is_error
        self.calls = []

    async def call_tool(self, name, args):
        self.calls.append((name, args))
        return _FakeResult(self._text, self._is_error)


def test_call_tool_passes_through_a_normal_ok_observation():
    client = _FakeClient("exit 0\nchanges: none\npolicy: ok", False)
    call_tool = do.make_call_tool(client)
    text, is_error = asyncio.run(call_tool(p.Action.run("ls")))
    assert not is_error
    assert "policy: ok" in text
    assert client.calls == [("run", {"command": "ls"})]


def test_call_tool_passes_through_a_recognised_pending_error():
    client = _FakeClient("exit 1\nchanges: none\npolicy: pending (threshold)", True)
    call_tool = do.make_call_tool(client)
    text, is_error = asyncio.run(call_tool(p.Action.run("cp /dev/null notes.txt")))
    assert is_error
    assert "policy: pending" in text


def test_call_tool_raises_on_an_error_with_no_parseable_policy_line():
    """An infrastructure error is not a policy authorization."""
    client = _FakeClient("Unable to execute the sandboxed step", True)
    call_tool = do.make_call_tool(client)
    with pytest.raises(do.DoSafetyError, match="no parseable policy status"):
        asyncio.run(call_tool(p.Action.run("ls")))
    assert loop.policy_of("Unable to execute the sandboxed step") == "unknown"


def test_call_tool_routes_typed_tool_calls_by_name_and_args():
    client = _FakeClient("exit 0\nchanges: none\npolicy: ok", False)
    call_tool = do.make_call_tool(client)
    action = p.Action.call("fs.read", path="notes.txt")
    asyncio.run(call_tool(action))
    assert client.calls == [("fs.read", {"path": "notes.txt"})]


# --- model driver: stateless prompt built fresh from `turns` each call ----------------------

def test_make_model_driver_sends_system_request_and_history_then_parses_the_reply(monkeypatch):
    tools = p.load_tools()
    seen = {}

    def fake_complete(url, model, messages, grammar, timeout):
        seen["messages"] = messages
        seen["grammar"] = grammar
        return "done\nall set"
    monkeypatch.setattr(do, "_chat_complete", fake_complete)

    next_action = do.make_model_driver(tools, "do the thing", "http://x", use_grammar=True)
    action = next_action((), "ok")
    assert action == p.Action.done("all set")
    assert seen["messages"][0]["role"] == "system"
    assert "Request: do the thing" in seen["messages"][1]["content"]
    assert seen["grammar"] is not None


def test_make_model_driver_replays_prior_turns_into_the_prompt(monkeypatch):
    tools = p.load_tools()
    seen = {}

    def fake_complete(url, model, messages, grammar, timeout):
        seen["messages"] = messages
        return "done\nok"
    monkeypatch.setattr(do, "_chat_complete", fake_complete)

    turn = loop.Turn(p.Action.run("ls"), "exit 0\nchanges: none\npolicy: ok", False)
    next_action = do.make_model_driver(tools, "goal", "http://x")
    next_action((turn,), "ok")
    rendered = [m["content"] for m in seen["messages"]]
    assert any("run\nls" in c for c in rendered)
    assert any("policy: ok" in c for c in rendered)


def test_make_model_driver_propagates_unparseable_replies_as_protocol_error(monkeypatch):
    tools = p.load_tools()
    monkeypatch.setattr(do, "_chat_complete", lambda *a, **k: "not a valid action at all!!")
    next_action = do.make_model_driver(tools, "goal", "http://x")
    with pytest.raises(p.ProtocolError):
        next_action((), "ok")


def test_make_model_driver_without_grammar_sends_no_grammar(monkeypatch):
    tools = p.load_tools()
    seen = {}

    def fake_complete(url, model, messages, grammar, timeout):
        seen["grammar"] = grammar
        return "done\nok"
    monkeypatch.setattr(do, "_chat_complete", fake_complete)
    next_action = do.make_model_driver(tools, "goal", "http://x", use_grammar=False)
    next_action((), "ok")
    assert seen["grammar"] is None


# --- record: versioned, private, round-trips --------------------------------------------

def test_each_clarification_without_session_retains_its_own_record(tmp_path):
    paths = []
    for request in ('first', 'second'):
        record = loop.Record(p.INTERFACE_VERSION, request, 'ask', 'Which file?', ())
        paths.append(do.save_record(tmp_path, 'no-session', request, tmp_path / 'ws', record))
    assert [do.load_record(path)['request'] for path in paths] == ['first', 'second']


def test_save_and_load_record_round_trips_and_is_private(tmp_path):
    record = loop.Record(p.INTERFACE_VERSION, "do the thing", "done", "all set", ())
    path = do.save_record(tmp_path, "123-abc", "do the thing", tmp_path / "ws", record)
    assert path.parent == tmp_path / "records"
    assert oct(path.parent.stat().st_mode)[-3:] == "700"
    assert oct(path.stat().st_mode)[-3:] == "600"
    loaded = do.load_record(path)
    assert loaded["terminal"] == "done"
    assert loaded["answer"] == "all set"
    assert loaded["schema_version"] == do.RECORD_SCHEMA_VERSION
    assert loaded["version"] == p.INTERFACE_VERSION
    assert loaded["session_id"] == "123-abc"


def test_load_record_refuses_an_unknown_schema_version(tmp_path):
    path = tmp_path / "r.json"
    path.write_text(json.dumps({"schema_version": 99, "version": p.INTERFACE_VERSION}))
    with pytest.raises(do.DoSafetyError, match="schema_version"):
        do.load_record(path)


def test_load_record_refuses_a_mismatched_interface_version(tmp_path):
    path = tmp_path / "r.json"
    path.write_text(json.dumps({"schema_version": do.RECORD_SCHEMA_VERSION, "version": 99}))
    with pytest.raises(do.DoSafetyError, match="interface v"):
        do.load_record(path)


# --- ground-truth session lookup: fail safe unless exactly one -----------------------------

def test_find_new_session_returns_none_when_no_session_was_ever_opened(tmp_path):
    assert do.find_new_session(tmp_path) is None
    assert do.find_new_session(tmp_path / "never-created") is None


def test_find_new_session_fails_safe_when_more_than_one_exist(tmp_path):
    for sid in ("1700000000-" + "a" * 16, "1700000001-" + "b" * 16):
        d = tmp_path / sid
        d.mkdir()
        (d / "meta.json").write_text("{}")
    with pytest.raises(do.DoSafetyError, match="found 2"):
        do.find_new_session(tmp_path)


def test_find_new_session_ignores_non_session_directories(tmp_path):
    (tmp_path / "records").mkdir()
    sid = "1700000000-" + "a" * 16
    d = tmp_path / sid
    d.mkdir()
    (d / "meta.json").write_text("{}")
    assert do.find_new_session(tmp_path) == d


def test_find_new_session_requires_meta_json(tmp_path):
    sid = "1700000000-" + "a" * 16
    (tmp_path / sid).mkdir()
    assert do.find_new_session(tmp_path) is None


# --- CLI dispatch: `lilguy do` reaches do.main, never the legacy runner --------------------

def test_cli_dispatches_do_to_do_main(monkeypatch):
    calls = []
    monkeypatch.setattr("lilguy.do.main", lambda argv: calls.append(argv) or 0)
    code = cli.main(["do", "--state-dir", "/tmp/x", "fix the thing"])
    assert code == 0
    assert calls == [["--state-dir", "/tmp/x", "fix the thing"]]


def test_cli_do_requires_state_dir(capsys):
    with pytest.raises(SystemExit):
        do.main(["fix the thing"])
    assert "--state-dir" in capsys.readouterr().err


def test_main_fails_safely_without_falling_back_when_sandbox_missing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(do, "check_sandbox", lambda: (_ for _ in ()).throw(do.DoSafetyError("no bwrap")))
    code = do.main(["fix it", "--state-dir", str(tmp_path / "state")])
    assert code == 2
    assert "failed safely" in capsys.readouterr().err
    assert not (tmp_path / "state").exists()  # nothing was staged, nothing was created


def test_main_fails_safely_without_falling_back_when_model_unreachable(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(do, "check_sandbox", lambda: None)
    monkeypatch.setattr(do, "check_model",
                        lambda url, timeout=5.0: (_ for _ in ()).throw(do.DoSafetyError("no model")))
    code = do.main(["fix it", "--state-dir", str(tmp_path / "state")])
    assert code == 2
    assert "failed safely" in capsys.readouterr().err
