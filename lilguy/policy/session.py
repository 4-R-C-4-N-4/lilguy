"""Per-step policy and frozen pending state; no model-facing approval authority."""
from __future__ import annotations

import contextlib
import json
import os
import time
from dataclasses import asdict, dataclass

from ..sandbox.backend import INCOMPLETE_TAGS, Backend, RunSpec, Session, StepResult
from .engine import Decision, Policy, evaluate_policies

# Tags meaning the step's effects cannot be trusted or bounded: always reject + roll back.
FAILED_TAGS = ("OOM", "DISK_CAP", "DIFF_ERROR", "RUNNER_ERROR", "MAX_LAYERS", "CGROUP_UNAVAILABLE")


@dataclass
class GuardedResult:
    result: StepResult
    decision: Decision


def append_audit(directory, record) -> None:
    record = dict(record)
    record["ts"] = time.time()
    record["session"] = directory.name
    with (directory / "audit.jsonl").open("a", encoding="utf8") as stream:
        stream.write(json.dumps(record, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


_PENDING_TAGS = ("SESSION_PENDING", "NETWORK_APPROVAL_REQUIRED")


def _refused(session, tag, message):
    return GuardedResult(StepResult(1, "", message, session.cwd, [tag], [], 0),
                         Decision("pending" if tag in _PENDING_TAGS else "reject", tag, message))


class GuardedSession:
    def __init__(self, backend: Backend, session: Session, policies: list[Policy] | None = None):
        self.backend = backend
        self.session = session
        # Mandatory floor + trusted policies (spec defaults if none) + workspace (tighten only).
        from .engine import policies_for
        self.policies = policies_for(session.workspace, policies)
        self.pending = (session.directory / "approval-request.json").exists()
        # Sessions created by layers.open_session are persisted so separate trusted
        # processes (approve / deny / continue) can act on them; plain test sessions are not.
        self.persisted = (session.directory / "progress.json").exists()
        self.generation = None
        if self.persisted:
            from ..sandbox import persist
            self.generation = persist.generation(session.directory)

    def _audit(self, record):
        append_audit(self.session.directory, record)

    def _hash(self, entries):
        # The approval request and committer must bind the exact same canonical bytes.
        from .commit import diff_hash
        return diff_hash(entries, self.session, self.backend.resolve)

    def _lock(self):
        if not self.persisted:
            return contextlib.nullcontext()
        from ..sandbox import persist
        return persist.session_lock(self.session.directory)

    def run(self, spec: RunSpec, *, typed_tool: str | None = None,
            tool_args: list | None = None) -> GuardedResult:
        """`tool_args` is the typed call as the human review shows it; callers redact free-text
        literals before passing it (see mcp_server.audit_args). It is never used to execute."""
        if self.session.closed:
            raise ValueError("session is closed")
        with self._lock():
            if self.persisted:
                from ..sandbox import persist
                if not self.session.directory.exists():
                    self.session.closed = True
                    return _refused(self.session, "SESSION_CHANGED", "session was discarded by another process")
                if persist.generation(self.session.directory) != self.generation:
                    # deny/rollback happened elsewhere; our in-memory layer list is stale.
                    return _refused(self.session, "SESSION_CHANGED",
                                    "session changed in another process; reopen it to continue")
            outcome = self._run_locked(spec, typed_tool, tool_args)
            if self.persisted:
                self.generation = persist.record_step(self.session)
            return outcome

    def _network_gate(self, spec: RunSpec):
        from . import approval
        mode = self.session.cfg.network
        if mode == "always":
            self._audit({"decision": "network_allowed_by_config", "command": approval.describe_command(spec)})
            return None
        if mode == "off":
            return _refused(self.session, "NETWORK_DISABLED", "network is turned off for this session")
        if approval.take_network_grant(self.session, spec):
            self._audit({"decision": "network_used", "command": approval.describe_command(spec)})
            return None
        request = approval.request_network(self.session, spec)
        self._audit({"decision": "network_requested", "command": request["command"],
                     "request_hash": request["request_hash"]})
        return _refused(self.session, "NETWORK_APPROVAL_REQUIRED",
                        "this command needs network; a human must allow it (lilguy approve)")

    def _run_locked(self, spec: RunSpec, typed_tool: str | None = None,
                    tool_args: list | None = None) -> GuardedResult:
        if self.pending:
            approval_path = self.session.directory / "approval.json"
            approved = json.loads(approval_path.read_text()) if approval_path.exists() else {}
            current_hash = self._hash(self.backend.session_diff(self.session))
            if approved.get("diff_hash") != current_hash:
                return _refused(self.session, "SESSION_PENDING", "session requires human decision")
            self._audit({"approval": approved, "decision": "approved"})
            self.pending = False
        if spec.network:
            refusal = self._network_gate(spec)
            if refusal is not None:
                return refusal
        # Any new execution invalidates the authority bound to the previous diff, and any
        # network grant that was not for this step.
        for name in ("approval.json", "approval-request.json", "network-request.json", "network-grant.json"):
            (self.session.directory / name).unlink(missing_ok=True)
        if typed_tool is None:
            command = asdict(spec)
        else:
            command = {"tool": typed_tool} if tool_args is None else {"tool": typed_tool, "args": tool_args}
        before = len(self.session.uppers)
        cwd = self.session.cwd
        result = self.backend.run(self.session, spec)
        try:
            session_diff = self.backend.session_diff(self.session)
            tags = {tag.split("(")[0] for tag in result.tags}
            stopped = [t for t in result.tags if t.split("(")[0] in INCOMPLETE_TAGS]
            new_session = session_diff
            # Rejections (protected paths, special files) are judged on everything.
            decision = evaluate_policies(result.step_diff, session_diff, self.policies)
            if decision.kind != "reject":
                from .commit import load_approved_fingerprints, unapproved_entries
                approved = load_approved_fingerprints(self.session.directory)
                new_session = unapproved_entries(session_diff, self.session, self.backend.resolve, approved)
                new_step = unapproved_entries(result.step_diff, self.session, self.backend.resolve, approved)
                # Approval thresholds only for changes a human has not already approved as they are now.
                decision = evaluate_policies(new_step, new_session, self.policies)
            if tags & set(FAILED_TAGS):
                decision = Decision("reject", "resource_limit", ",".join(result.tags))
            elif stopped and decision.kind != "reject":
                # Stopped for time: keep the partial work and let a human look at it.
                decision = Decision("pending", "incomplete_step", ",".join(stopped))
            if decision.kind == "reject":
                if len(self.session.uppers) > before:
                    self.backend.rollback_step(self.session)
                self.session.cwd = cwd
                result.cwd = cwd
            elif decision.kind == "pending":
                request = {"session_id": self.session.directory.name,
                           "workspace": str(self.session.workspace),
                           "diff_hash": self._hash(session_diff), "rule": decision.rule,
                           "summary": decision.detail, "paths": [e.path for e in session_diff],
                           "changes": [asdict(e) for e in session_diff],
                           "new_paths": [e.path for e in new_session],
                           "stopped": stopped, "command": command,
                           "exit_code": result.exit_code, "layers": len(self.session.uppers),
                           "step_paths": [e.path for e in result.step_diff], "ts": time.time()}
                path = self.session.directory / "approval-request.json"
                with path.open("x", encoding="utf8") as stream:
                    json.dump(request, stream, sort_keys=True)
                    stream.flush()
                    os.fsync(stream.fileno())
                self.pending = True
            self._audit({"tool": typed_tool or "exec", "args": command, "exit": result.exit_code,
                         "duration_ms": result.duration_ms, "step_diff": [asdict(e) for e in result.step_diff],
                         "tags": result.tags, "decision": decision.kind, "rule": decision.rule})
            return GuardedResult(result, decision)
        except Exception:
            # Missing audit/policy evidence is never permission to keep running.
            self.pending = True
            raise

    def discard(self):
        self.backend.discard(self.session)
