"""Contracts shared by sandbox, effect policy and future MCP tools."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

# Hard wall-clock ceiling for one step. Liveness checks (idle/stall) normally
# stop a stuck command long before this; it is only the last backstop.
MAX_WALL_S = 24 * 3600

# Steps stopped for time reasons keep their partial layer; policy marks them pending.
INCOMPLETE_TAGS = ("TIMEOUT", "IDLE_TIMEOUT", "STALLED")


@dataclass
class DiffEntry:
    op: Literal["added", "modified", "meta", "deleted", "trashed", "replaced_dir"]
    path: str
    kind: Literal["file", "dir", "symlink", "special"]
    size_before: int | None = None
    size_after: int | None = None
    mode_before: int | None = None
    mode_after: int | None = None
    symlink_target: str | None = None
    is_binary: bool = False


@dataclass
class RunSpec:
    shell: str | None = None
    argv: list[str] | None = None
    pipe: list[list[str]] | None = None
    timeout_s: float | None = None
    network: bool = False   # step asks for network; granted per SessionConfig.network

    def __post_init__(self):
        if sum(x is not None for x in (self.shell, self.argv, self.pipe)) != 1:
            raise ValueError("exactly one of shell, argv, pipe is required")
        if self.argv is not None and not self.argv:
            raise ValueError("argv cannot be empty")
        if self.pipe is not None and (not self.pipe or any(not s for s in self.pipe)):
            raise ValueError("pipeline stages cannot be empty")
        if self.timeout_s is not None and not 0 < self.timeout_s <= MAX_WALL_S:
            raise ValueError(f"timeout must be in (0, {MAX_WALL_S}]")


@dataclass
class SessionConfig:
    state_dir: Path | None = None
    mount_path: Literal["real", "short"] = "real"
    timeout_s: float = 600          # hard wall budget per step
    idle_timeout_s: float = 60      # no CPU and no progress for this long -> stop, keep partial work
    stall_timeout_s: float = 30     # CPU busy but no progress for this long -> freeze and ask (or stop)
    heartbeat_s: float = 30         # how often a monitor is told the step is still running
    max_output_bytes: int = 256_000
    max_file_bytes: int = 128 * 1024 * 1024
    max_upper_bytes: int = 256 * 1024 * 1024
    memory_bytes: int = 1024 * 1024 * 1024
    max_processes: int = 64
    max_layers: int = 64
    allow_rlimits_fallback: bool = False
    protected: tuple[str, ...] = (".git", ".lilguy", ".env", "**/.env")
    # Steps that ask for network: "off" never, "ask" (default) a human allows full network for that
    # one step, "always" every such step gets it. Only trusted config sets this, never the workspace.
    network: str = "ask"

    def __post_init__(self):
        if self.network not in ("off", "ask", "always"):
            raise ValueError("network must be off, ask or always")
        if self.mount_path not in ("real", "short"):
            raise ValueError("mount_path must be real or short")
        if not 0 < self.timeout_s <= MAX_WALL_S:
            raise ValueError(f"timeout must be in (0, {MAX_WALL_S}]")
        for value in (self.idle_timeout_s, self.stall_timeout_s, self.heartbeat_s):
            if not 0 < value <= MAX_WALL_S:
                raise ValueError("liveness intervals must be positive and bounded")
        for value in (self.max_output_bytes, self.max_file_bytes, self.max_upper_bytes,
                      self.memory_bytes, self.max_processes, self.max_layers):
            if value <= 0:
                raise ValueError("limits must be positive")
        if self.max_layers > 64:
            raise ValueError("at most 64 layers")
        if self.state_dir is not None and not self.state_dir.is_absolute():
            raise ValueError("state_dir must be absolute")


@dataclass
class Session:
    workspace: Path
    directory: Path
    cfg: SessionConfig
    uppers: list[Path] = field(default_factory=list)  # oldest first
    cwd: str = "."
    closed: bool = False


@dataclass
class StepResult:
    exit_code: int
    stdout: str
    stderr: str
    cwd: str
    tags: list[str]
    step_diff: list[DiffEntry]
    duration_ms: int


@dataclass
class StepStatus:
    """What a monitor sees about a running step. Observed host-side, never self-reported."""
    elapsed_s: float
    cpu_s: float | None            # None when no cgroup (rlimits fallback)
    cpu_percent: float | None      # recent, 100 = one core
    output_bytes: int
    upper_bytes: int
    upper_files: int
    seconds_since_progress: float
    last_output_line: str          # untrusted command output, already clipped
    state: Literal["running", "stalled", "idle"]


class Monitor(Protocol):
    """Trusted caller hooks (CLI / agent-loop process), never the model."""
    def heartbeat(self, status: StepStatus) -> None: ...
    def stalled(self, status: StepStatus) -> Literal["continue", "stop"]: ...


class Backend(Protocol):
    def open_session(self, workspace: Path, cfg: SessionConfig) -> Session: ...
    def run(self, s: Session, spec: RunSpec) -> StepResult: ...
    def rollback_step(self, s: Session) -> None: ...
    def session_diff(self, s: Session) -> list[DiffEntry]: ...
    def resolve(self, s: Session, rel: str) -> Path | None: ...
    def discard(self, s: Session) -> None: ...
