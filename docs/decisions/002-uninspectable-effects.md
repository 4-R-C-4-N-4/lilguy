# 002: Reject effects that cannot be inspected; do not pretend they are harmless

Status: conservative safety behavior, with exact spec-acceptance difference recorded. **Accepted by Ivy 2026-11-18.**

Real target-host execution of corpus item 16 (`chmod -R 000 src`) revokes directory traversal permission before recursive chmod can visit the children. The command itself reports permission denied. The host diff walker likewise cannot enumerate the private upper directory. Guessing an empty diff would permit uninspected effects; temporarily widening modes while computing a diff would risk losing the true permission changes.

The backend instead returns `DIFF_ERROR`, rejects and rolls back that step. The host workspace remains unchanged, and subsequent steps can continue. This meets the corpus's overall rejected-or-pending safety condition but differs from row 16's suggested pending outcome. No claim is made that the command completed successfully or that every row has its suggested exact label.

Private cleanup restores owner search/write permissions only on disposable session directories before removing them. It never chmods the actual workspace and never follows symlink entries. A regression reproduces both the previous cleanup leak and successful continuation after rejection.

Similarly, the fork-bomb fixture can exit zero when background children are denied further forks. Containment evidence is the exact transient scope's verified TasksMax/MemoryMax, observed fork refusal, inactive scope after exit, and unchanged host canary—not the shell's exit code alone.

The guide requires a generated minimal `/etc/passwd` and `/etc/group`; accordingly an in-sandbox link to `/etc/passwd` may read synthetic sandbox identity data, not the host passwd file. Spec corpus item 11's assumption that no passwd file is mounted is superseded by that explicit implementation requirement. Host secrets and parent workspace paths remain invisible.
