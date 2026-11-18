# 001: Resolve executable-bit example versus chmod bypass acceptance

Status: conservative implementation clarification; Q3 threshold sign-off remains Ivy's. **Accepted by Ivy 2026-11-18.**

Spec §9 shows `mode_change: executable_bit`, while §12 case 16 requires `chmod -R 000 src` to become pending. A non-executable 0644 source file changed to 000 changes no executable bits. Testing reproduced an `ok` result with an executable-bit-only check.

The engine retains executable-bit approval and additionally requires approval whenever existing read/write/execute permissions are removed (`permission_reduction`). This satisfies case 16 without changing D1–D11, granting the model authority, or weakening any default. Permission additions without execute-bit changes remain unaffected unless `mode_change: any` is configured. This conservative clarification is explicitly recorded rather than silently changing a scope decision.

A regression test covers 0644 → 000. Policy-threshold tuning remains gated on measured pending/reject rates and Ivy's Q3 decision.

Also note: spec §9's `any_delete_outside` example requires approval for even one source-file deletion; IMPLEMENTATION §9.5's suggestion that one deletion is automatically committed is not generally true with that default. The engine follows the explicit default YAML and reports the matching rule; no test silently disables it.
