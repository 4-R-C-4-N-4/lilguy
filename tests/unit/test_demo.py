"""`lilguy demo`: practice folder contents and the printed walkthrough."""
from lilguy import cli, demo


def test_demo_creates_the_files_and_prints_commands(tmp_path, capsys):
    target = tmp_path / "practice"
    assert cli.main(["demo", str(target)]) == 0
    for name, text in demo.FILES.items():
        assert (target / name).read_text() == text
    out = capsys.readouterr().out
    assert f"cd {target}" in out
    assert 'lilguy ask "What is the timeout in staging.conf?"' in out
    assert "lilguy commit " in out and "lilguy deny " in out and "Apply? [y/N]" in out


def test_demo_refuses_a_non_empty_folder(tmp_path, capsys):
    (tmp_path / "keep.txt").write_text("mine")
    assert demo.main([str(tmp_path)]) == 2
    assert "not empty" in capsys.readouterr().err
    assert (tmp_path / "keep.txt").read_text() == "mine"


def test_demo_files_match_what_the_walkthrough_asks_about():
    text = "\n".join(c for _, cmds in demo.STEPS for c in cmds)
    for name in ("staging.conf", "access.log", "notes/agenda.md", "reports/2024-q1.csv"):
        assert name in text and name in demo.FILES
