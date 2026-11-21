# Historical v0.1 material — DO NOT IMPORT OR EXECUTE

These files are archival text, not a runtime, test suite, or supported command path.
The former host executor was not sandboxed. No compatibility shim is provided.
Reproduction belongs on the original git revision (before cleanup, `31dde30`),
not by importing this directory or putting it on PYTHONPATH. Dataset commands must
never be run on the host, even when reproducing historical experiments.

`eval.py` was also retired because it directly instantiated the host executor.
Its old oracle tests and the host-shell/agent contract tests are deliberately outside
pytest collection. Relevant non-executing digest/convention assertions were preserved
in `tests/unit/test_retired_runtime.py`. Guarded protocol, loop, sandbox, approval,
MCP, and factory safety tests remain active and unchanged; they supersede the old
host-agent semantics. No safety acceptance is implied by archival cleanup.
