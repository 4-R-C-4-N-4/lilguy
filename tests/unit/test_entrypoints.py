"""Public command dispatch must not accidentally execute a legacy goal."""
from unittest.mock import patch

from lilguy import cli


def test_probe_dispatches_without_constructing_model():
    with patch("lilguy.probe.main", create=True, return_value=1) as probe:
        assert cli.main(["probe", "--json"]) == 1
    probe.assert_called_once_with(["--json"])



def test_sandbox_run_dispatches_without_legacy_runner():
    with patch("lilguy.sandbox.cli.main", create=True, return_value=0) as sandbox:
        assert cli.main(["sandbox-run", "--workspace", ".", "--cmd", "true"]) == 0
    sandbox.assert_called_once_with(["--workspace", ".", "--cmd", "true"])
