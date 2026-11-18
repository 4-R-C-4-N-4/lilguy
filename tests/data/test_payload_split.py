"""find -exec / xargs / sudo payloads are their own commands, not flags of the wrapper."""
import pytest

from lilguy.data.parse import parse_command


def cmds(cmd):
    return [(c["utility"], c.get("via"), c["flags"]) for c in parse_command(cmd)["commands"]]


def test_find_exec_payload_is_split_out():
    out = cmds(r"find . -name '*.tmp' -exec rm -rf {} \;")
    assert out[0][0] == "find" and out[0][1] is None
    assert out[0][2] == {"name": "*.tmp", "exec": "rm"}
    assert out[1] == ("rm", "find -exec", {"r": True, "f": True})


def test_find_exec_plus_terminator_and_following_tests():
    out = cmds("find src -type f -exec grep -l TODO {} + -print")
    assert out[0][2] == {"type": "f", "exec": "grep", "print": True}
    assert out[1] == ("grep", "find -exec", {"l": True})


@pytest.mark.parametrize("action", ["execdir", "ok", "okdir"])
def test_other_exec_actions(action):
    out = cmds(f"find . -{action} chmod 644 {{}} \\;")
    assert out[0][2] == {action: "chmod"}
    assert out[1][:2] == ("chmod", f"find -{action}")


def test_two_execs():
    out = cmds(r"find . -exec ls {} \; -exec wc -l {} \;")
    assert [u for u, *_ in out] == ["find", "ls", "wc"]
    assert out[2] == ("wc", "find -exec", {"l": True})


def test_xargs_payload_with_options():
    out = cmds("find . -name '*.c' -print0 | xargs -0 -I {} -n 1 grep -c main {}")
    assert out[1] == ("xargs", None, {"0": True, "I": "{}", "n": "1", "payload": "grep"})
    assert out[2] == ("grep", "xargs", {"c": True})


def test_xargs_without_payload_defaults_to_echo():
    out = cmds("ls | xargs")
    assert out[1] == ("xargs", None, {"payload": "echo"})
    assert out[2] == ("echo", "xargs", {})


def test_sudo_payload():
    out = cmds("sudo -u www-data rm -rf /var/cache/x")
    assert out[0] == ("sudo", None, {"u": "www-data", "payload": "rm"})
    assert out[1] == ("rm", "sudo", {"r": True, "f": True})


def test_utilities_list_and_flags_by_utility_include_payloads():
    parsed = parse_command(r"find . -exec rm {} \;")
    assert parsed["utilities"] == ["find", "rm"]
    assert "rm" in parsed["flags_by_utility"]
    assert "i" not in parsed["flags_by_utility"]["find"]


def test_unterminated_exec_is_marked_not_guessed():
    out = cmds("find . -exec rm {}")
    assert out[0][2]["exec"] == "rm"
    assert out[1][:2] == ("rm", "find -exec")
