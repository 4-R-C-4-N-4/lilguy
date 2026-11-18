# 006: Network for a step is a configuration; default: a human allows full network for one step

Status: implemented and tested. Decided by Ivy 2026-11-18 ("make this a configuration, default ask full network one turn").

## Setting

`SessionConfig.network` (`sandbox-run --network-mode`). It is set by trusted config only; a workspace's own config cannot enable network.

| Value | A step that asks for network (`RunSpec.network`, `sandbox-run --network`) |
|---|---|
| `off` | refused, nothing runs (`NETWORK_DISABLED`) |
| `ask` (default) | does not run; a request is written (`NETWORK_APPROVAL_REQUIRED`, pending). `lilguy approve <session>` shows the exact command and folder and asks; `lilguy deny` drops it |
| `always` | runs with network, audited |

Steps that do not ask for network never get it.

## What "one step" means

A grant is bound to a hash of the exact command, the working directory, the session and its current position (number of layers). It is used up by that step. It does not cover a different command, and expires if any other step runs first. Grants, requests and their use are recorded in the session audit.

## What a networked step can and cannot do

- **Can:** full network, using the host's network namespace. This includes services listening on this machine's localhost (the approval prompt says so).
- **Still enforced:**
  - the copy-on-write workspace, read-only system and protected paths, and resource limits;
  - after-the-fact review of its file effects (a networked step that writes `.env` is rejected, as usual);
  - **no access to the host session's abstract Unix sockets**, where D-Bus, X11 and similar can listen;
  - **no signals to processes outside the sandbox.**

  The last two come from Landlock scoping (ABI ≥ 6). They now apply to every step, and network is refused on kernels that lack them.
- Filesystem Unix sockets (e.g. `/run/user/…/bus`) are not mounted in the sandbox.

## Tests

- `tests/unit/test_network_gate.py`: modes, one-step binding, expiry, CLI approve/deny, audit.
- `tests/sandbox/test_network.py`, against real bubblewrap and a real localhost server:
  - an ordinary step cannot connect;
  - a networked step can;
  - a networked step cannot reach a host abstract socket;
  - effects are still sandboxed;
  - the full CLI flow: request → approve → run once → asks again.
