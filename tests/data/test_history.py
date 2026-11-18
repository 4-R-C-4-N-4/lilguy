"""Local shell history: parsed for coverage only; the summary must never contain raw arguments."""
import json
import sqlite3

from lilguy.data import history

SECRET_HISTORY = """\
#1700000000
ls -la
#1700000001
git status
git commit -m "fix: secret project codename ZEBRA"
mysql -u root -pS3cretPass mydb
curl -H "Authorization: Bearer abc123token" https://internal.example/api
export GH_TOKEN=ghp_AAAABBBBCCCC
ghp_ZZZZpastedbymistake
find /home/ivy/private-notes -name '*.md' -exec rm {} \\;
"""


def test_bash_history_with_timestamps():
    assert history.parse_history("#1700000000\nls\n#1700000001\ngit status\n") == ["ls", "git status"]


def test_zsh_extended_history_and_continuations():
    text = ": 1700000000:0;ls -la\n: 1700000001:0;echo a \\\nb\n"
    assert history.parse_history(text) == ["ls -la", "echo a \\\nb"]


def test_atuin_database(tmp_path):
    db = tmp_path / "history.db"
    con = sqlite3.connect(db)
    con.execute("create table history (command text, timestamp integer)")
    con.executemany("insert into history values (?, ?)", [("ls", 2), ("git status", 1)])
    con.commit()
    con.close()
    assert history.read_atuin(db) == ["git status", "ls"]


def _summary():
    vocab = {"ls": {"l", "a"}, "git": {"m"}, "find": {"name", "exec"}, "rm": set(), "curl": {"H"},
             "mysql": {"u"}}
    known = {"ls", "git", "mysql", "curl", "export", "find", "rm"}
    return history.safe_summary(history.parse_history(SECRET_HISTORY), toolset={"ls": ["l", "a"]},
                                public_vocab=vocab, is_known_utility=known.__contains__)


def test_summary_never_contains_arguments_values_or_unknown_names():
    text = json.dumps(_summary())
    for secret in ("S3cretPass", "abc123token", "ghp_", "ZEBRA", "private-notes", "internal.example",
                   "/home/", "mydb", "Bearer", "root"):
        assert secret not in text, secret


def test_summary_counts_what_it_can_name():
    summary = _summary()
    assert summary["commands"] == 8
    assert summary["utilities"]["git"] == 2
    assert summary["utilities"]["<other>"] == 1          # the pasted token typed as a command
    assert summary["flags"]["mysql"] == {"u": 1, "<unlisted>": 1}   # -pS3cretPass is not shown
    assert summary["wrappers"]["find -exec"] == 1
    assert summary["covered"] == 1                         # ls -la
    assert all(":" not in item or item.split(":")[-1] != "S3cretPass"
               for step in summary["curve"] for item in step["added"])


def test_refuses_to_write_outside_private_reports(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        history.write_private_report({"commands": 0}, tmp_path / "reports" / "history.json")
    out = tmp_path / "reports" / "private" / "history.json"
    history.write_private_report({"commands": 0}, out)
    assert json.loads(out.read_text()) == {"commands": 0}
    assert out.stat().st_mode & 0o077 == 0
