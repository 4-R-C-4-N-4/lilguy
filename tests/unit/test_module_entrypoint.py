"""Smoke test the public Python module entrypoint."""
import os
import subprocess
import sys


def test_module_entrypoint_help_lists_commands():
    result = subprocess.run([sys.executable, "-m", "lilguy", "--help"],
                            capture_output=True, text=True, timeout=10, env=os.environ.copy())
    assert result.returncode == 0, result.stderr
    assert "probe" in result.stdout
    assert "eval" not in result.stdout
    assert "sandbox-run" in result.stdout
    assert "--unsafe-legacy" not in result.stdout
