"""Public command dispatch must not accidentally execute a legacy goal."""
from unittest.mock import patch

from lilguy import cli


def test_probe_dispatches_without_constructing_model():
    with patch("lilguy.probe.main", create=True, return_value=1) as probe:
        assert cli.main(["probe", "--json"]) == 1
    probe.assert_called_once_with(["--json"])


def test_eval_dispatches_to_existing_harness():
    with patch("lilguy.eval.main", return_value=0) as evaluate:
        assert cli.main(["eval", "--backend", "scripted"]) == 0
    evaluate.assert_called_once_with(["--backend", "scripted"])


def test_sandbox_run_dispatches_without_legacy_runner():
    with patch("lilguy.sandbox.cli.main", create=True, return_value=0) as sandbox:
        assert cli.main(["sandbox-run", "--workspace", ".", "--cmd", "true"]) == 0
    sandbox.assert_called_once_with(["--workspace", ".", "--cmd", "true"])


def test_run_requires_explicit_unsafe_legacy_opt_in(capsys):
    assert cli.main(["run", "write a file"]) == 2
    assert "--unsafe-legacy" in capsys.readouterr().err


def test_run_dispatches_only_with_explicit_unsafe_opt_in():
    with patch("lilguy.cli.legacy_main", return_value=0) as legacy:
        assert cli.main(["run", "--unsafe-legacy", "a goal", "--cwd", "."]) == 0
    legacy.assert_called_once_with(["a goal", "--cwd", "."])
