"""P0 keeps the v0.1 contracts stable until the P5 port."""
import pytest

from lilguy.actions import InvalidAction, parse_action
from lilguy.agent import Agent
from lilguy.backends import Scripted
from lilguy.digest import digest
from lilguy.memory import ConventionStore, Entry
from lilguy.shell import run


@pytest.mark.parametrize("raw", ["nothing", '{}', '{"action":"nope"}', '{"action":"run","arg":""}'])
def test_invalid_actions_are_rejected(raw):
    with pytest.raises(InvalidAction):
        parse_action(raw)


def test_action_accepts_fenced_json_and_preserves_shell_quotes():
    action = parse_action('```json\n{"action":"run","cmd":"echo \'hello\'","expect":"output"}\n```')
    assert action.arg == "echo 'hello'"
    assert action.expect == "output"


def test_digester_exposes_failure_and_clips_output():
    result = digest(1, "\n".join(str(n) for n in range(100)), "cat: missing: No such file or directory")
    assert result.outcome == "fail"
    assert "ENOENT(missing)" in result.tags
    assert "76 lines hidden" in result.text


def test_project_conventions_win_ties():
    store = ConventionStore([Entry({"test"}, "Run tests.", "global"),
                             Entry({"test"}, "Run tests.", "project")])
    assert store.retrieve("test")[0].scope == "project"


def test_three_invalid_actions_stop_the_agent(tmp_path):
    class InvalidBackend:
        def complete(self, system, prompt):
            return "not an action"
    result = Agent(InvalidBackend(), str(tmp_path)).run("do nothing")
    assert result.final == "invalid"
    assert result.invalid_actions == 3


def test_ask_can_continue_after_answer(tmp_path):
    backend = Scripted([{"action": "ask", "arg": "Which?"}, {"action": "done"}])
    result = Agent(backend, str(tmp_path), ask=lambda _: "this one").run("choose")
    assert result.final == "done"
    assert result.steps[0].observation == "USER: this one"


def test_shell_carries_cwd_but_not_environment(tmp_path):
    (tmp_path / "sub").mkdir()
    first = run("cd sub; export LILGUY_TEST_VAR=private", str(tmp_path), str(tmp_path))
    assert first.cwd == str(tmp_path / "sub")
    second = run('printf %s "${LILGUY_TEST_VAR-unset}"', first.cwd, str(tmp_path))
    assert second.stdout.strip() == "unset"


def test_shell_timeout_is_tagged(tmp_path):
    result = run("sleep 10", str(tmp_path), str(tmp_path), timeout=0.05)
    assert result.exit_code == 124
    assert any(tag.startswith("TIMEOUT") for tag in result.tags)
