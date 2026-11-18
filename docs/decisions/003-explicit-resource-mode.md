# 003: Make the resource mode explicit; default to guaranteed cgroup scoping

Status: conservative execution choice; rlimits-only remains an explicit opt-in fallback. **Accepted by Ivy 2026-11-18.**

The guide prefers cgroups and permits rlimit fallback. Review reproduced a gap in the first backend: it could call the scope wrapper without checking usable delegation, and the wrapper returned an unwrapped command when systemd-run was absent. A broken user bus usually failed before executing the command, but that accidental failure is not an explicit guarantee.

`SessionConfig.allow_rlimits_fallback` defaults to false. Before creating a step layer or launching any payload, the backend checks a real disposable user scope. No usable scope produces `CGROUP_UNAVAILABLE` and no payload launch. If the wrapper disappears after the check, launch is refused rather than silently dropping the scope.

A trusted caller may opt into `allow_rlimits_fallback=True`; this produces `DEGRADED_RLIMITS` in the step result, preserves the same namespace/Landlock isolation and strict in-sandbox rlimits, and makes no cgroup MemoryMax/TasksMax/CPUQuota claim. The model cannot set SessionConfig, and the preview CLI does not expose a degradation switch. No stress test uses this mode; only a fixed harmless echo/cwd fixture verifies its visibility.

This is stricter than an automatic fallback but does not remove the guide's fallback path. The capability probe continues to show cgroup delegation as optional host information; actual execution states its resource mode explicitly. Results reported for this target host use working cgroup scoping.

The earlier claim that RLIMIT_NPROC is scoped by a PID namespace was inaccurate: UID/user-namespace accounting is distinct from PID visibility. Documentation no longer treats it as a replacement for per-step TasksMax.
