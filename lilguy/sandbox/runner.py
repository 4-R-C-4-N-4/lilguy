"""Host-side bwrap orchestration. No host-shell or empty-diff fallback."""
from __future__ import annotations

import json
import os
import selectors
import signal
import stat
import subprocess
import tempfile
import time
from functools import lru_cache
from pathlib import Path

from . import bwrap as bw, diff, layers, limits
from .backend import INCOMPLETE_TAGS, RunSpec, Session, SessionConfig, StepResult, StepStatus

_SHIM = Path(__file__).with_name("landlock.py")

# How often the upper-layer directory (and the cgroup cpu counter) are
# resampled while a step is running. Walking the overlay upper dir is not
# free; this bounds that cost regardless of select()'s shorter polling tick.
_SAMPLE_INTERVAL_S = 0.25


@lru_cache(maxsize=4)
def _require_capabilities(binary: str):
    from ..probe import run_probe
    failures = [f"{r.name}: {r.detail}" for r in run_probe() if r.required and r.status == "fail"]
    if failures:
        raise RuntimeError("exec isolation incomplete: " + "; ".join(failures))


class BwrapBackend:
    def __init__(self, monitor=None):
        self._monitor = monitor

    def open_session(self, workspace: Path, cfg: SessionConfig) -> Session:
        workspace = Path(workspace).resolve()
        bw.validate_workspace(workspace, cfg.state_dir)
        if workspace == Path.home().resolve():
            raise ValueError("the user's entire home is not an acceptable workspace")
        _require_capabilities(bw.bwrap_path())
        session = layers.open_session(workspace, cfg)
        # These are the only passwd/group entries visible inside the sandbox.
        (session.directory / "passwd").write_text(f"lilguy:x:{os.getuid()}:{os.getgid()}:sandbox:/home/sandbox:/bin/bash\n")
        (session.directory / "group").write_text(f"lilguy:x:{os.getgid()}:\n")
        self._cgroup_available(session)
        return session

    @staticmethod
    def _cgroup_available(session):
        environment = tuple(os.environ.get(key) for key in ("PATH", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS"))
        cached = getattr(session, "_cgroup_proof", None)
        if cached is None or cached[0] != environment:
            cached = (environment, limits.cgroup_scope_available())
            session._cgroup_proof = cached
        return cached[1]

    def run(self, s: Session, spec: RunSpec) -> StepResult:
        start = time.monotonic()
        if s.closed:
            raise ValueError("session is closed")
        has_cgroup = self._cgroup_available(s)
        if not has_cgroup and not s.cfg.allow_rlimits_fallback:
            return StepResult(125, "", "cgroup delegation unavailable; resource containment cannot be guaranteed",
                              s.cwd, ["CGROUP_UNAVAILABLE"], [], int((time.monotonic() - start) * 1000))
        if len(s.uppers) >= s.cfg.max_layers:
            return StepResult(-1, "", "layer limit reached; commit or discard this session", s.cwd,
                              ["MAX_LAYERS"], [], int((time.monotonic() - start) * 1000))
        previous_cwd = s.cwd
        lower = list(s.uppers)
        upper = layers.new_layer(s)
        work = upper.parent / "work"
        dest = bw.dest_path(s.workspace, s.cfg)
        payload = json.dumps({"shell": spec.shell, "argv": spec.argv, "pipe": spec.pipe,
                              "timeout_s": None}).encode()
        if len(payload) > 1024 * 1024:
            layers.rollback_step(s)
            raise ValueError("RunSpec exceeds 1 MiB")
        result_r, result_w = os.pipe()
        proc = None
        tags = ([] if has_cgroup else ["DEGRADED_RLIMITS"]) + (["NETWORK"] if spec.network else [])
        buffers = {"stdout": bytearray(), "stderr": bytearray(), "result": bytearray()}
        total = {key: 0 for key in buffers}
        unit = None
        try:
            with tempfile.TemporaryFile(dir=s.directory) as spec_file:
                spec_file.write(payload)
                spec_file.seek(0)
                entry = ["/usr/bin/python3", "-I", "/opt/lilguy/landlock.py",
                         "--chdir", str(Path(dest) / s.cwd),
                         "--spec-fd", str(spec_file.fileno()), "--result-fd", str(result_w),
                         "--max-output-bytes", str(s.cfg.max_output_bytes),
                         "--max-file-bytes", str(s.cfg.max_file_bytes),
                         "--memory-bytes", str(s.cfg.memory_bytes),
                         "--max-processes", str(s.cfg.max_processes)]
                for path in (dest, "/tmp", "/home/sandbox"):
                    entry += ["--write", path]
                if spec.network:
                    entry += ["--allow-net"]
                protected = tuple(dict.fromkeys((*s.cfg.protected, ".git", ".lilguy", ".env",
                                                  *bw.find_env_files(s.workspace))))
                from dataclasses import replace
                cfg = replace(s.cfg, protected=protected)
                argv = bw.build_argv(workspace=s.workspace, cfg=cfg, network=spec.network,
                                     lowers=[s.workspace, *lower], upper=upper, work=work, entry_argv=entry)
                extras = ["--ro-bind", str(_SHIM), "/opt/lilguy/landlock.py",
                          "--ro-bind", str(s.directory / "passwd"), "/etc/passwd",
                          "--ro-bind", str(s.directory / "group"), "/etc/group"]
                for path in ("/etc/ssl", "/etc/alternatives"):
                    if os.path.exists(path):
                        extras += ["--ro-bind", path, path]
                argv = argv[:-len(entry)] + extras + entry
                if has_cgroup:
                    argv = limits.wrap_with_cgroup_scope(argv, cfg)
                unit = next((arg.split("=", 1)[1] for arg in argv if arg.startswith("--unit=")), None)
                if has_cgroup and unit is None:
                    raise RuntimeError("cgroup wrapper vanished before launch; refusing unscoped execution")
                proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, pass_fds=(spec_file.fileno(), result_w),
                                        start_new_session=True)
                os.close(result_w)
                result_w = -1
                budget = spec.timeout_s or cfg.timeout_s
                kill_time = None
                tracker = _LivenessTracker(unit=unit, has_cgroup=has_cgroup, upper=upper,
                                           idle_timeout_s=cfg.idle_timeout_s,
                                           stall_timeout_s=cfg.stall_timeout_s,
                                           heartbeat_s=cfg.heartbeat_s,
                                           monitor=self._monitor, start=start,
                                           output_cap=cfg.max_output_bytes)
                last_sample = 0.0
                with selectors.DefaultSelector() as selector:
                    for stream, name in ((proc.stdout, "stdout"), (proc.stderr, "stderr"), (result_r, "result")):
                        descriptor = stream if isinstance(stream, int) else stream.fileno()
                        os.set_blocking(descriptor, False)
                        selector.register(stream, selectors.EVENT_READ, name)
                    while selector.get_map():
                        now = time.monotonic()
                        if kill_time is None:
                            effective_elapsed = (now - start) - tracker.total_frozen
                            if effective_elapsed >= budget:
                                tags.append("TIMEOUT")
                                self._kill(proc, unit)
                                kill_time = now
                            elif now - last_sample >= _SAMPLE_INTERVAL_S:
                                last_sample = now
                                allocated, largest, _files = _dir_usage(upper)
                                if allocated > cfg.max_upper_bytes or largest > cfg.max_file_bytes:
                                    tags.append("DISK_CAP")
                                    self._kill(proc, unit)
                                    kill_time = now
                                else:
                                    verdict = tracker.sample(now, total, buffers)
                                    if verdict == "idle":
                                        tags.append("IDLE_TIMEOUT")
                                        self._kill(proc, unit)
                                        kill_time = time.monotonic()
                                    elif verdict == "stalled":
                                        tags.append("STALLED")
                                        self._kill(proc, unit)
                                        kill_time = time.monotonic()
                        if kill_time is not None and now - kill_time > 2:
                            # A forged/retained result fd must never make the host wait forever.
                            break
                        for key, _ in selector.select(.05):
                            fd = key.fileobj if isinstance(key.fileobj, int) else key.fileobj.fileno()
                            try:
                                chunk = os.read(fd, 65536)
                            except BlockingIOError:
                                continue
                            if not chunk:
                                selector.unregister(key.fileobj)
                                continue
                            name = key.data
                            total[name] += len(chunk)
                            cap = 65536 if name == "result" else cfg.max_output_bytes
                            remaining = cap - len(buffers[name])
                            if remaining > 0:
                                buffers[name].extend(chunk[:remaining])
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self._kill(proc, unit)
                    proc.wait(timeout=2)
        except BaseException:
            if proc is not None and proc.poll() is None:
                self._kill(proc, unit)
                proc.wait(timeout=2)
            layers.rollback_step(s)
            raise
        finally:
            os.close(result_r)
            if result_w >= 0:
                os.close(result_w)
            if proc is not None:
                for stream in (proc.stdout, proc.stderr):
                    if stream is not None:
                        stream.close()
        stdout = buffers["stdout"].decode("utf8", "replace")
        stderr = buffers["stderr"].decode("utf8", "replace")
        if any(total[name] > s.cfg.max_output_bytes for name in ("stdout", "stderr")):
            tags.extend(["TRUNCATED", "OUTPUT_TRUNCATED"])
        exit_code = proc.returncode
        stopped = (*INCOMPLETE_TAGS, "DISK_CAP")
        try:
            if total["result"] > 65536:
                raise ValueError("oversized runner result")
            report = json.loads(buffers["result"])
            if not isinstance(report, dict) or type(report.get("exit_code")) is not int:
                raise ValueError("malformed runner result")
            if report.get("error"):
                stderr += "\n" + str(report["error"])
                tags.append("RUNNER_ERROR")
            elif not any(t in tags for t in stopped):
                s.cwd = self._safe_cwd(report.get("cwd"), dest, previous_cwd)
            if exit_code == 0:
                exit_code = report["exit_code"]
        except (ValueError, TypeError):
            if not any(t in tags for t in stopped):
                tags.append("RUNNER_ERROR")
                stderr += "\nmissing or invalid runner result"
        allocated, largest, _files = _dir_usage(upper)
        if allocated > s.cfg.max_upper_bytes or largest > s.cfg.max_file_bytes:
            if "DISK_CAP" not in tags:
                tags.append("DISK_CAP")
        if "DISK_CAP" in tags or "RUNNER_ERROR" in tags:
            layers.rollback_step(s)
            s.cwd = previous_cwd
            entries = []
            exit_code = exit_code or 125
        elif any(t in tags for t in INCOMPLETE_TAGS):
            # Stopped for time/liveness reasons: keep the partial layer. The
            # sandboxed shell never got to report back, so cwd stays put.
            s.cwd = previous_cwd
            exit_code = 124
            try:
                entries = diff.step_diff(s, upper)
            except (OSError, diff.DiffError) as exc:
                layers.rollback_step(s)
                s.cwd = previous_cwd
                entries = []
                tags.append("DIFF_ERROR")
                stderr += f"\nuninspectable effects: {exc}"
                exit_code = 125
        else:
            try:
                entries = diff.step_diff(s, upper)
            except (OSError, diff.DiffError) as exc:
                layers.rollback_step(s)
                s.cwd = previous_cwd
                entries = []
                tags.append("DIFF_ERROR")
                stderr += f"\nuninspectable effects: {exc}"
                exit_code = 125
        return StepResult(exit_code, stdout, stderr, s.cwd, tags, entries,
                          int((time.monotonic() - start) * 1000))

    def rollback_step(self, s):
        layers.rollback_step(s)

    def session_diff(self, s):
        return diff.session_diff(s)

    def resolve(self, s, rel):
        return layers.resolve(s, rel)

    def discard(self, s):
        layers.discard(s)

    @staticmethod
    def _kill(proc, unit=None):
        if unit is not None:
            # Thaw defensively first: a frozen scope should still accept
            # `systemctl kill`, but never let a stuck freeze block the kill.
            try:
                subprocess.run(["systemctl", "--user", "thaw", f"{unit}.scope"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                pass
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        if unit is not None:
            # Only the unique transient scope created for this step, never a host-wide unit.
            try:
                subprocess.run(["systemctl", "--user", "kill", "--kill-whom=all", "--signal=KILL",
                                f"{unit}.scope"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                pass

    @staticmethod
    def _safe_cwd(reported, dest, fallback):
        if not isinstance(reported, str) or not reported.startswith("/"):
            return fallback
        try:
            relative = Path(reported).relative_to(dest)
        except ValueError:
            return fallback
        if ".." in relative.parts:
            return fallback
        return relative.as_posix() if relative.parts else "."


class _LivenessTracker:
    """Decides idle/stall/continue for one running step, host-side only.

    Progress = new stdout/stderr bytes that are still being captured, or the
    upper layer reaching a new high in allocated bytes or file count. Output
    past the capture cap and create/delete churn are not progress: nobody can
    see the former and the latter accumulates nothing. CPU activity alone never
    counts as progress. Without a
    cgroup we cannot read CPU at all, so (per the shared contract) any
    no-progress stretch past stall_timeout_s is treated as busy-and-stalled
    rather than idle, since idle vs busy can't be told apart in that mode.
    """

    def __init__(self, *, unit, has_cgroup, upper, idle_timeout_s, stall_timeout_s,
                 heartbeat_s, monitor, start, output_cap):
        self.unit = unit
        self.has_cgroup = has_cgroup
        self.upper = upper
        self.idle_timeout_s = idle_timeout_s
        self.stall_timeout_s = stall_timeout_s
        self.heartbeat_s = heartbeat_s
        self.monitor = monitor
        self.start = start
        self.output_cap = output_cap
        self.total_frozen = 0.0
        self.last_progress_time = start
        self.last_output_total = 0
        self.last_upper_bytes = 0
        self.last_upper_files = 0
        self.max_upper_bytes = 0
        self.max_upper_files = 0
        self.cpu_path = None
        self.cpu_last_usec = None
        self.cpu_last_time = None
        self.cpu_s = None
        self.cpu_percent = None
        self.last_output_line = ""
        self.last_heartbeat = start

    def _read_cpu_usec(self):
        if self.cpu_path is None:
            try:
                out = subprocess.run(
                    ["systemctl", "--user", "show", f"{self.unit}.scope", "-p", "ControlGroup", "--value"],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=2,
                ).stdout.strip()
            except (OSError, subprocess.TimeoutExpired):
                out = ""
            if not out:
                return None  # scope may not have appeared yet; try again later
            self.cpu_path = f"/sys/fs/cgroup{out}/cpu.stat"
        try:
            with open(self.cpu_path) as fh:
                for line in fh:
                    if line.startswith("usage_usec"):
                        return int(line.split()[1])
        except (OSError, ValueError):
            return None
        return None

    def _update_cpu(self, now):
        if not self.has_cgroup or not self.unit:
            self.cpu_s = None
            self.cpu_percent = None
            return
        usec = self._read_cpu_usec()
        if usec is None:
            return
        self.cpu_s = usec / 1_000_000
        if self.cpu_last_usec is not None and now > self.cpu_last_time:
            delta_usec = usec - self.cpu_last_usec
            delta_t = now - self.cpu_last_time
            self.cpu_percent = (delta_usec / 1_000_000) / delta_t * 100
        self.cpu_last_usec = usec
        self.cpu_last_time = now

    def _busy(self):
        if not self.has_cgroup:
            return True  # cannot distinguish idle from busy without cgroup cpu
        return self.cpu_percent is not None and self.cpu_percent >= 50

    def _last_line(self, buffers):
        combined = bytes(buffers["stdout"]) + bytes(buffers["stderr"])
        for line in reversed(combined.splitlines()):
            if line.strip():
                return line.decode("utf8", "replace")[:200]
        return ""

    def _status(self, now, total, buffers, state):
        return StepStatus(
            elapsed_s=now - self.start,
            cpu_s=self.cpu_s,
            cpu_percent=self.cpu_percent,
            output_bytes=total["stdout"] + total["stderr"],
            upper_bytes=self.last_upper_bytes,
            upper_files=self.last_upper_files,
            seconds_since_progress=now - self.last_progress_time,
            last_output_line=self._last_line(buffers),
            state=state,
        )

    def _freeze(self):
        if not self.unit:
            return False
        try:
            r = subprocess.run(["systemctl", "--user", "freeze", f"{self.unit}.scope"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
            return r.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    def _thaw(self):
        if not self.unit:
            return
        try:
            subprocess.run(["systemctl", "--user", "thaw", f"{self.unit}.scope"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            pass

    def _ask_monitor(self, status):
        if self.monitor is None:
            return "stop"
        try:
            decision = self.monitor.stalled(status)
        except Exception:
            return "stop"
        return decision if decision == "continue" else "stop"

    def sample(self, now, total, buffers):
        """Call ~every _SAMPLE_INTERVAL_S. Returns None/'idle'/'stalled'."""
        allocated, _largest, files = _dir_usage(self.upper)
        if allocated > self.max_upper_bytes or files > self.max_upper_files:
            self.last_progress_time = now
            self.max_upper_bytes = max(self.max_upper_bytes, allocated)
            self.max_upper_files = max(self.max_upper_files, files)
        self.last_upper_bytes, self.last_upper_files = allocated, files

        output_total = min(total["stdout"], self.output_cap) + min(total["stderr"], self.output_cap)
        if output_total != self.last_output_total:
            self.last_progress_time = now
        self.last_output_total = output_total

        self._update_cpu(now)

        if self.monitor is not None and now - self.last_heartbeat >= self.heartbeat_s:
            self.last_heartbeat = now
            try:
                self.monitor.heartbeat(self._status(now, total, buffers, "running"))
            except Exception:
                pass

        busy = self._busy()
        since_progress = now - self.last_progress_time
        threshold = self.stall_timeout_s if busy else self.idle_timeout_s
        if since_progress < threshold:
            return None

        if not busy:
            return "idle"

        # Busy, no progress for stall_timeout_s: freeze and ask.
        status = self._status(now, total, buffers, "stalled")
        frozen_ok = self._freeze()
        freeze_start = time.monotonic()
        decision = self._ask_monitor(status)
        if frozen_ok:
            # Only time the command could not run is free; if freezing failed it kept running.
            self.total_frozen += time.monotonic() - freeze_start
        if decision == "continue":
            if frozen_ok:
                self._thaw()
            self.last_progress_time = time.monotonic()
            self.cpu_last_usec = None
            self.cpu_last_time = None
            return None
        if frozen_ok:
            self._thaw()
        return "stalled"


def _dir_usage(path):
    allocated = largest = files = 0
    for root, dirs, filenames in os.walk(path, followlinks=False):
        for name in dirs + filenames:
            try:
                info = (Path(root) / name).lstat()
            except FileNotFoundError:
                continue
            allocated += info.st_blocks * 512
            if stat.S_ISREG(info.st_mode):
                largest = max(largest, info.st_size)
                files += 1
    return allocated, largest, files
