"""Runaway loops that fake progress must still be caught by the stall check.

Each test has a short hard wall (timeout_s) as a safety backstop; the assertion
is that the stall check fires first, well before that.
"""
import time

import pytest

from lilguy.sandbox.backend import RunSpec, SessionConfig
from lilguy.sandbox.runner import BwrapBackend
from tests.sandbox.test_liveness import _check_no_leftover_scopes  # noqa: F401 (autouse fixture)

pytestmark = pytest.mark.sandbox


@pytest.fixture
def backend_session(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    backend = BwrapBackend()
    session = backend.open_session(ws, SessionConfig(state_dir=tmp_path / "state", stall_timeout_s=1,
                                                     idle_timeout_s=30, timeout_s=8, max_output_bytes=4096))
    yield backend, session
    backend.discard(session)


def test_endless_output_beyond_the_capture_cap_is_not_progress(backend_session):
    backend, session = backend_session
    start = time.monotonic()
    result = backend.run(session, RunSpec(shell="while :; do echo spam; done"))
    assert "STALLED" in result.tags, result.tags
    assert time.monotonic() - start < 6


def test_create_delete_churn_is_not_progress(backend_session):
    backend, session = backend_session
    start = time.monotonic()
    result = backend.run(session, RunSpec(shell="while :; do echo x > churn; rm churn; done"))
    assert "STALLED" in result.tags, result.tags
    assert time.monotonic() - start < 6


def test_steadily_accumulating_work_is_still_progress(backend_session):
    backend, session = backend_session
    result = backend.run(session, RunSpec(shell="for i in $(seq 1 20); do echo $i > f$i; sleep 0.15; done"))
    assert result.exit_code == 0 and not result.tags, (result.tags, result.stderr)
