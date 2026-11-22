# Permission wording: diagnostic and guarded rescue

On the same draft-file listing, two trained MiniCPM revisions were asked for modes 600, 640, 644, 660 and 664, first in words and then explicitly in octal. The criterion here is exactly one `chmod` command with the correct numeric argument and file, not a semantic grade on arbitrary shell. The forms are paired on one development fixture, not independent tasks.

| Training seed | R8 words | R8 octal | R9 words | R9 octal |
|---|---:|---:|---:|---:|
| 42 | 2/5 | 5/5 | 1/5 | 5/5 |
| 43 | 2/5 | 5/5 | 1/5 | 4/5 |

R9 does not always output 664; both seeds output 664 for owner-only, but 640 for owner+group-read. Seed 43's octal 644 response named an extra operand. Raw stock responses often have extra commands and are not comparable as task scores using this strict metric. No predicted actions were executed in the prefix probe. Source: `dev/permission_contrast.py`; reports under the existing r8/r9 assessment directories (`permission-contrast-6h2vlb37`, `permission-contrast-y8si8_wl`).

Guarded follow-up: from scratch on fresh copies of the original fixture, append only `The requested octal mode is 600.` to the original request. Keep the existing grader, oracle, null control, approval policy and multi-turn runner. R8 passed both wordings on both seeds. R9 staged 644→664 and failed the unaided wording on both seeds, then staged 644→600 and passed with the explicit mode on both. All eight episodes had agreeing controls, no infrastructure failures and preserved originals. These are staged effects, never commits. Source traces: `reports/factory/permission-rescue-j7ex47r5/{42,43}-{control,treatment}/{words,explicit}.json`.

Conclusion: supplying the permission argument rescues this task. It neither solves general permission interpretation nor establishes that a particular training example caused the regression. Keep r8 the baseline. Test a human-selected owner/group/other permission choice mapped to a mode by trusted code on fresh fixtures before proposing a served interface change. Never infer a broad permission grant from ambiguous prose.
