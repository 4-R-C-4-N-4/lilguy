"""`lilguy demo [DIR]`: a small practice folder and the commands to try in it.

Every request below was run against the released model while preparing v1: the questions
answered correctly, the edits staged exactly the intended diff, and the move stopped for
approval because it deletes a file. That is a demonstration, not a
guarantee -- the model is small and can still get things wrong, which is why nothing it
does reaches your files until you commit it.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

FILES = {
    "staging.conf": "timeout=30\nretry=2\nhost=staging.internal\n",
    "access.log": ("GET /index.html 200\nGET /about 200\nPOST /login 302\n"
                   "GET /missing 404\nGET /old-page 404\nGET /contact 200\n"),
    "notes/agenda.md": "# Team meeting\n\n- Status updates\n- Release plan\n",
    "reports/2024-q1.csv": "name,amount\nalpha,10\nbeta,20\n",
    "reports/2024-q2.csv": "name,amount\nalpha,12\nbeta,25\n",
}

STEPS = [
    ("Ask questions (read-only; the answer is quoted from a command that ran)", [
        'lilguy ask "What is the timeout in staging.conf?"',
        'lilguy ask "How many lines in access.log contain 404?"',
        'lilguy ask "Which reports are in the reports folder?"',
    ]),
    ("Make a change (staged in the sandbox; your files stay untouched)", [
        'lilguy do "Change timeout from 30 to 45 in staging.conf. Leave retry unchanged."',
        'lilguy do "Add \'Budget review\' as the last item of the agenda in notes/agenda.md."',
    ]),
    ("Review and keep it (copy the session path lilguy printed)", [
        "lilguy diff SESSION      # look again",
        "lilguy commit SESSION    # write it into the folder (asks you to confirm)",
        "lilguy undo              # list commits you can reverse",
    ]),
    ("Something that needs your approval (a move deletes the original)", [
        'lilguy do "Move reports/2024-q1.csv into a new folder reports/archive."',
        "lilguy approve SESSION   # or: lilguy deny SESSION",
        "lilguy commit SESSION",
    ]),
]


def make(directory: Path) -> None:
    if directory.exists() and any(directory.iterdir()):
        raise FileExistsError(f"{directory} exists and is not empty; pick a new folder")
    for name, text in FILES.items():
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


def instructions(directory: Path) -> str:
    lines = [f"Practice folder ready: {directory}", "", f"  cd {directory}", ""]
    for title, commands in STEPS:
        lines.append(title + ":")
        lines.extend(f"  {command}" for command in commands)
        lines.append("")
    lines.append("When you are done: lilguy stop   (frees the GPU/CPU the model uses)")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="lilguy demo", description="Make a practice folder and print commands to try in it.")
    ap.add_argument("directory", nargs="?", type=Path, default=Path("lilguy-demo"),
                    help="where to create the practice folder (default: ./lilguy-demo)")
    args = ap.parse_args(argv)
    directory = args.directory.expanduser().resolve()
    try:
        make(directory)
    except OSError as exc:
        print(f"lilguy demo: {exc}", file=sys.stderr)
        return 2
    print(instructions(directory))
    return 0
