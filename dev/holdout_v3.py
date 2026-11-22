"""Interface-v3 modes and oracles for the frozen held-out suite (no task, file or grader changes).

ROADMAP/INTERFACE-V3 authorised this recalibration as part of v3, before any model runs on the
held-out suite: v3 answers a question with the quoted output of the last command, so the ten
read-only questions (family G) are issued with `lilguy ask` and their scripted solution ends
on a command that prints the value. Everything else keeps its frozen v2 oracle in `do` mode.
Family B (the named file is absent) is graded on the `ask` text, the one terminal whose own
words lilguy shows the user (see fast12_runner.interface_grade). Nothing here derives from a
model run: it was written from the task definitions alone and calibrated with the scripted
and false-done controls (tests/sandbox/test_holdout_v3_live.py).
"""
from dev.holdout_corpus import _G

ASK = frozenset(f"holdout_g_readonly_{i:02d}" for i in range(len(_G)))

ORACLES = {
    f"holdout_g_readonly_{i:02d}": (f"run\ngrep '^{key}=' {fname}", "done")
    for i, (fname, _content, key, _val, _question) in enumerate(_G)
}
