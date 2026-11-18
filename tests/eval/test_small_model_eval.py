import asyncio
import json
from types import SimpleNamespace

import pytest

from dev.small_model_eval import (
    FIXTURES, TOOLSET, Effects, action_loop, configure_ollama, grade, inspect_effects, oracle_case, snapshot,
)
from lilguy.mcp_server import load_tools
from lilguy.policy.session import append_audit
from lilguy.sandbox import layers, persist
from lilguy.sandbox.backend import SessionConfig


def effect(fixture, **overrides):
    return Effects(**({"entries": fixture.expected_entries, "staged": fixture.expected_bytes,
                       "originals_ok": True, "pending": False} | overrides))


@pytest.mark.parametrize("responses,termination,invalid", [
    (['{"action":"done"}'], "done", 0),
    (['{"action":"done","question":"extra"}'], "budget_exhausted", 1),
    (['{"action":"exec","arguments":{}}'], "budget_exhausted", 1),
    (['{"action":"done","action":"done"}'], "budget_exhausted", 1),
    (['{"action":"fs.edit","arguments":{}}'], "budget_exhausted", 1),
    (['{"action":"fs.read","arguments":{"path":"file","offset":1.0}}'], "budget_exhausted", 1),
    (['no', '{"action":"done"}'], "done", 1),
])
def test_evidence_of_exact_edit_cannot_substitute_for_clean_done(responses, termination, invalid):
    async def tool(*args):
        pytest.fail("unexpected tool call")

    fixture = FIXTURES[0]
    replies = iter(responses)
    run = asyncio.run(action_loop(lambda _: next(replies), tool, load_tools(TOOLSET), [], len(responses)))
    result = grade(fixture, run, effect(fixture))
    assert result["effects_ok"]
    assert result["termination"] == termination
    assert result["invalid_actions"] == invalid
    assert result["pass"] == (termination == "done" and invalid == 0)


@pytest.mark.parametrize("overrides", [
    {"entries": ()},
    {"entries": (("modified", "unrelated", "file"),)},
    {"staged": b"wrong bytes"},
    {"originals_ok": False},
    {"unexpected_steps": (("modified", "unexpected", "file"),)},
])
def test_done_cannot_substitute_for_exact_edit(overrides):
    fixture = FIXTURES[0]
    result = grade(fixture, [{"action": "done"}], effect(fixture, **overrides))
    assert result["termination"] == "done"
    assert not result["effects_ok"]
    assert not result["pass"]


@pytest.mark.parametrize("trace,passes", [
    ([{"action": "ask", "question": "Which environment, staging or production?"}], True),
    ([{"action": "ask", "question": "Can you clarify?"}], False),
    ([{"action": "ask", "question": "Which retry value?"}], False),
    ([{"action": "ask", "question": "Which retry value for the deployment?"}], False),
    ([{"action": "done"}], False),
    ([{"action": "fs.edit"}, {"action": "ask", "question": "Which environment?"}], False),
])
def test_ambiguous_task_requires_relevant_question_and_no_write(trace, passes):
    fixture = FIXTURES[-1]
    assert grade(fixture, trace, effect(fixture))["pass"] == passes


@pytest.mark.parametrize("formatting", ["named", "neutral"])
@pytest.mark.parametrize("context", ["task", "listing", "open"])
@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda fixture: fixture.id)
def test_offline_oracle_controls(fixture, context, formatting):
    result = asyncio.run(oracle_case(fixture, context, formatting, budget=8))
    assert result["pass"]
    prompt = json.dumps(result["initial_messages"])
    assert ('Example with fs.find' in prompt) == (formatting == "named")
    assert ("Workspace listing" in prompt) == (context == "listing")
    assert ("Open file" in prompt) == (context == "open")
    for path in fixture.paths:
        assert (path in prompt) == (context != "task")


def test_exact_edit_using_last_turn_is_an_effect_only_pass():
    fixture = FIXTURES[0]
    result = asyncio.run(oracle_case(fixture, "open", "neutral", budget=1))
    assert result["effects_ok"]
    assert result["termination"] == "budget_exhausted"
    assert result["invalid_actions"] == 0
    assert not result["pass"]


def test_repeated_tool_action_and_tracer_validation_failure():
    async def tool(name, args):
        assert (name, args) == ("fs.read", {"path": "/outside"})
        return "Expected a workspace-relative path", True

    trace = asyncio.run(action_loop(
        lambda _: '{"action":"fs.read","arguments":{"path":"/outside"}}',
        tool, load_tools(TOOLSET), [], 2,
    ))
    fixture = FIXTURES[0]
    result = grade(fixture, trace, effect(fixture))
    assert result["invalid_actions"] == 2
    assert result["repeated_actions"] == 1
    assert result["tool_errors"] == 2


def test_ollama_request_configuration(monkeypatch):
    calls = []

    def request(port, path, payload=None):
        calls.append((port, path, payload))
        return {
            "/api/tags": {"models": [{"name": "synthetic:tag", "digest": "synthetic-digest", "size": 1}]},
            "/api/version": {"version": "test"},
            "/api/chat": {"message": {"content": '{"action":"done"}'}},
        }[path]

    monkeypatch.setattr("dev.small_model_eval.ollama_request", request)
    config, respond = configure_ollama(SimpleNamespace(port=11434, model="synthetic:tag", seed=7))
    messages = [{"role": "user", "content": "Synthetic task"}]
    assert respond(messages) == '{"action":"done"}'
    assert config["model_digest"] == "synthetic-digest"
    assert [path for _, path, _ in calls] == ["/api/tags", "/api/version", "/api/chat"]
    assert calls[-1][2] == config["request"] | {"messages": messages}
    assert config["request"]["options"]["seed"] == 7


def test_inspect_persisted_effects_and_originals(tmp_path):
    fixture = FIXTURES[0]
    workspace = tmp_path / "workspace"
    state = tmp_path / "state"
    for path, content in fixture.files.items():
        file = workspace / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(content)
    baseline = snapshot(workspace)
    session = layers.open_session(workspace, SessionConfig(state_dir=state, network="off"))
    staged = layers.new_layer(session) / fixture.paths[0]
    staged.parent.mkdir()
    staged.write_bytes(fixture.expected_bytes)
    persist.record_step(session)
    append_audit(session.directory, {"decision": "ok", "step_diff": []})

    trace = [{"action": "done"}]
    assert grade(fixture, trace, inspect_effects(fixture, workspace, state, baseline))["pass"]
    (session.directory / "approval-request.json").write_text("{}")
    pending = grade(fixture, trace, inspect_effects(fixture, workspace, state, baseline))
    assert pending["effects_ok"] and not pending["pass"]
    (workspace / "notes.txt").write_bytes(b"changed")
    assert not inspect_effects(fixture, workspace, state, baseline).originals_ok


def test_corpus_formatting_uses_the_training_system_prompt_verbatim():
    from dev.small_model_corpus import system_prompt
    from dev.small_model_eval import PAIRED_FIXTURES

    for fixture in (FIXTURES[0], PAIRED_FIXTURES[0]):
        result = asyncio.run(oracle_case(fixture, "open", "corpus", budget=8))
        assert result["pass"]
        assert result["initial_messages"][0]["content"] == system_prompt(load_tools(TOOLSET))


def test_corpus_formatting_is_selectable_but_not_a_default(tmp_path):
    from dev.small_model_eval import FORMATS, main

    assert "corpus" not in FORMATS
    out = tmp_path / "rows.jsonl"
    assert main(["--suite", "paired", "--formatting", "corpus", "--out", str(out)]) == 0
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert len(rows) == 4 and {row["formatting"] for row in rows} == {"corpus"}


def test_tool_observations_are_returned_in_one_shared_format():
    from dev.small_model_eval import observation_message

    async def tool(name, args):
        return "exit=0\n(no output)", False

    messages = []

    def respond(history):
        messages[:] = history
        return '{"action":"fs.read","arguments":{"path":"a"}}' if len(history) == 0 else '{"action":"done"}'

    asyncio.run(action_loop(respond, tool, load_tools(TOOLSET), [], 2))
    assert messages[-1] == {"role": "user", "content": observation_message("exit=0\n(no output)")}
