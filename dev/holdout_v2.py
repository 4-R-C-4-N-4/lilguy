"""Held-out suite v2: 100 operator-written tasks, frozen before any r10/v4 model runs on them.

Written for the 2.0 decision (docs/plan/INTERFACE-V4.md, step 7). It is independent of every
development fixture, of the corpus generators, and of held-out v1, whose families it does not
reuse. It is never used for training, tuning or failure analysis. Its families cover everyday
work, including the two skills revision 10 added, in new domains and with new phrasing:

  A  change_one_setting           -- one value in a small config, other keys untouched
  B  change_in_named_block        -- the same line in two blocks; only the named block changes
  C  append_lines                 -- add two or three lines at the end of a file
  D  quote_a_value                -- a question answered by a value in a file (ask mode)
  E  count_matching_lines         -- a question answered by a count (ask mode)
  F  create_exact_file            -- create a file with exactly the given lines
  G  move_into_folder             -- moving a file deletes the original, so it waits for approval
  H  named_file_absent            -- the named file does not exist; ask instead of guessing
  I  find_misplaced_file          -- the named file lives in a subfolder; find it, then edit
  J  workspace_protected_file     -- workspace policy protects the file; the edit is refused

Each task carries its interface-v4 mode and oracle: a question ends on a command that prints
exactly the answer, and a final done is replayed bare. Same pure `grade` contract as
dev/holdout_corpus.py.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from dev.holdout_corpus import _Expected


@dataclass(frozen=True)
class Task:
    id: str
    request: str
    files: dict
    oracle: tuple


_TASKS: list = []
_EXPECTED: dict = {}
_ASK: set = set()


def _add(task, expected, mode="do"):
    assert task.id not in _EXPECTED, task.id
    _TASKS.append(task)
    _EXPECTED[task.id] = expected
    if mode == "ask":
        _ASK.add(task.id)


def _block(key, text):
    return f"{key} <<<\n{text.rstrip(chr(10))}\n>>>"


# --- A change_one_setting --------------------------------------------------------------------
_A = [
    ("kiln.toml", "temperature = 1180\nramp = slow\n", "temperature = 1180", "temperature = 1220"),
    ("aquarium.conf", "light_hours=8\nfilter=on\n", "light_hours=8", "light_hours=10"),
    ("bakery.ini", "[oven]\nloaves=24\nrye=yes\n", "loaves=24", "loaves=30"),
    ("telescope.cfg", "mount: equatorial\nfocal: 900\n", "focal: 900", "focal: 1200"),
    ("loom.properties", "warp.threads=320\nweft.color=indigo\n", "weft.color=indigo", "weft.color=saffron"),
    ("beehive.yaml", "frames: 10\nqueen: marked\n", "frames: 10", "frames: 12"),
    ("orchard.conf", "irrigation=weekly\nrows=14\n", "irrigation=weekly", "irrigation=daily"),
    ("darkroom.ini", "[timer]\ndevelop=480\nstop=30\n", "develop=480", "develop=540"),
    ("choir.toml", "altos = 6\nbasses = 4\n", "basses = 4", "basses = 5"),
    ("pottery.cfg", "glaze: celadon\nfirings: 2\n", "glaze: celadon", "glaze: tenmoku"),
]
_A_SAY = ["Raise the kiln temperature to 1220 in {f}.", "Set light_hours to 10 in {f}.",
          "Make it 30 loaves in {f}.", "Change the focal length in {f} to 1200.",
          "Switch the weft colour in {f} to saffron.", "Use 12 frames in {f}.",
          "Water the orchard daily: update {f}.", "Develop for 540 seconds instead: edit {f}.",
          "We have 5 basses now; update {f}.", "Use tenmoku glaze in {f}."]
for i, (f, text, old, new) in enumerate(_A):
    _add(Task(f"heldout2_a_setting_{i:02d}", _A_SAY[i].format(f=f), {f: text},
              (f"tool fs.read\npath: {f}", f"tool fs.edit\npath: {f}\nold: {old}\nnew: {new}",
               f"tool fs.read\npath: {f}", "done")),
         _Expected(terminal="done", changes={f: text.replace(old, new, 1)}))

# --- B change_in_named_block (the same line occurs twice) --------------------------------------
_B = [
    ("cluster.toml", ["[staging]\nreplicas = 2\n", "[production]\nreplicas = 2\n"], 1, "replicas = 2", "replicas = 6",
     "Scale production to 6 replicas in {f}; staging stays at 2."),
    ("menu.md", ["### Lunch\n- soup: no\n", "### Dinner\n- soup: no\n"], 1, "- soup: no", "- soup: yes",
     "Add soup to dinner in {f} (set it to yes there only)."),
    ("crew.txt", ["name: Odile\nshift: night\n", "name: Ravi\nshift: night\n"], 0, "shift: night", "shift: day",
     "Odile moves to the day shift; update {f}. Ravi stays on nights."),
    ("routes.ini", ["[north]\nbus=12\n", "[south]\nbus=12\n"], 0, "bus=12", "bus=31",
     "The north route now uses bus 31 in {f}. South keeps 12."),
    ("garden.yaml", ["tomatoes:\n  water: low\n", "basil:\n  water: low\n"], 1, "  water: low", "  water: high",
     "Basil needs high water in {f}; tomatoes stay low."),
    ("classes.md", ["## Monday\n- room: B2\n", "## Thursday\n- room: B2\n"], 1, "- room: B2", "- room: C7",
     "Thursday's class moved to room C7; edit {f} and leave Monday."),
    ("printers.conf", ["[lobby]\ntoner=ok\n", "[office]\ntoner=ok\n"], 1, "toner=ok", "toner=low",
     "Mark the office printer's toner as low in {f}."),
    ("pets.txt", ["pet: Miso\nfed: no\n", "pet: Tofu\nfed: no\n"], 0, "fed: no", "fed: yes",
     "Miso has been fed: record it in {f}. Tofu has not."),
    ("stages.toml", ["[build]\ntimeout = 10\n", "[test]\ntimeout = 10\n"], 1, "timeout = 10", "timeout = 25",
     "Give the test stage a timeout of 25 in {f}; build keeps 10."),
    ("rooms.ini", ["[attic]\nheater=off\n", "[cellar]\nheater=off\n"], 0, "heater=off", "heater=on",
     "Turn the attic heater on in {f}; the cellar stays off."),
]
for i, (f, blocks, target, old, new, say) in enumerate(_B):
    text = "\n".join(blocks)
    header = blocks[target].split("\n", 1)[0] + "\n"
    after = text.replace(header + old + "\n", header + new + "\n", 1)
    _add(Task(f"heldout2_b_block_{i:02d}", say.format(f=f), {f: text},
              (f"tool fs.read\npath: {f}",
               f"tool fs.edit\npath: {f}\n{_block('old', header + old)}\n{_block('new', header + new)}",
               f"tool fs.read\npath: {f}", "done")),
         _Expected(terminal="done", changes={f: after}))

# --- C append_lines --------------------------------------------------------------------------
_C = [
    ("packing.md", "# Packing\n- tent\n", ["- stove", "- matches"], 'Add "stove" and "matches" to the end of {f} as list items.'),
    ("visitors.csv", "name,date\nIlse,03-02\n", ["Bram,03-09", "Chen,03-11"], "Append rows Bram,03-09 and Chen,03-11 to {f}."),
    ("allowlist.txt", "alpha.example\n", ["beta.example", "gamma.example"], "Add beta.example and gamma.example on their own lines at the end of {f}."),
    ("minutes.md", "## Decisions\n- adopt tabs\n", ["- review in May", "- budget frozen"], 'Append two decisions to {f}: "review in May" and "budget frozen".'),
    ("readings.log", "07:00 12.1\n", ["08:00 12.4", "09:00 12.9", "10:00 13.0"], "Log three more readings at the end of {f}: 08:00 12.4, 09:00 12.9 and 10:00 13.0."),
    ("songs.txt", "Blue Hour\n", ["Salt Road", "Paper Moon"], "Add Salt Road and then Paper Moon to the end of {f}."),
    ("shortcuts.conf", "save=ctrl+s\n", ["undo=ctrl+z", "redo=ctrl+y"], "Append undo=ctrl+z and redo=ctrl+y to {f}."),
    ("credits.md", "Thanks to:\n- Wren\n", ["- Juno", "- Pell"], "Credit Juno and Pell too: add them as list items at the end of {f}."),
    ("queue.txt", "job-101\n", ["job-102", "job-103", "job-104"], "Queue job-102, job-103 and job-104 at the end of {f}, one per line."),
    ("glossary.md", "**kiln**: a furnace\n", ["**slip**: liquid clay", "**bisque**: first firing"], "Add two entries to the end of {f}: **slip**: liquid clay, then **bisque**: first firing."),
]
for i, (f, text, lines, say) in enumerate(_C):
    quoted = " ".join("'" + line + "'" for line in lines)
    _add(Task(f"heldout2_c_append_{i:02d}", say.format(f=f), {f: text},
              (f"tool fs.read\npath: {f}", f"run\nprintf '%s\\n' {quoted} >> {f}", f"tool fs.read\npath: {f}", "done")),
         _Expected(terminal="done", changes={f: text + "".join(line + "\n" for line in lines)}))

# --- D quote_a_value (ask) -------------------------------------------------------------------
_D = [
    ("boat.ini", "hull=fiberglass\nmast=aluminium\n", "mast", "aluminium", "What is the mast made of, according to boat.ini?"),
    ("library.conf", "late_fee=0.25\nloan_days=21\n", "loan_days", "21", "How many loan days does library.conf allow?"),
    ("station.toml", 'call_sign = "KX4QR"\nband = "40m"\n', "call_sign", "KX4QR", "What call sign is set in station.toml?"),
    ("lab.cfg", "centrifuge: 4000rpm\nfreezer: -80\n", "freezer", "-80", "What temperature is the freezer set to in lab.cfg?"),
    ("farm.ini", "goats=7\nhens=19\n", "hens", "19", "How many hens does farm.ini list?"),
    ("studio.conf", "mic=ribbon\nmonitor=nearfield\n", "mic", "ribbon", "Which microphone type is configured in studio.conf?"),
    ("trail.yaml", "length: 14km\ngrade: moderate\n", "grade", "moderate", "What grade is the trail in trail.yaml?"),
    ("press.ini", "paper=cotton\nink=walnut\n", "ink", "walnut", "Which ink does press.ini specify?"),
    ("clinic.toml", "open = 08:30\nclose = 17:00\n", "close", "17:00", "When does the clinic close, per clinic.toml?"),
    ("radio.cfg", "freq: 101.7\nmode: fm\n", "freq", "101.7", "What frequency is radio.cfg tuned to?"),
]
for i, (f, text, key, val, question) in enumerate(_D):
    pattern = rf"(?<![\w.-]){re.escape(val)}(?![\w.])"
    _add(Task(f"heldout2_d_value_{i:02d}", question, {f: text}, (f"run\ngrep '^{key}' {f}", "done")),
         _Expected(terminal="done", changes={}, answer_patterns=(pattern,)), mode="ask")

# --- E count_matching_lines (ask) ------------------------------------------------------------
_E = [
    ("orders.log", ["ok 1", "late 2", "ok 3", "late 4", "late 5"], "late", "How many orders in orders.log were late?"),
    ("seeds.txt", ["kale", "kale", "chard", "leek"], "kale", "How many lines of seeds.txt say kale?"),
    ("tickets.csv", ["id,state", "1,open", "2,closed", "3,open", "4,open"], ",open", "How many tickets are open in tickets.csv?"),
    ("birds.txt", ["wren", "robin", "wren", "wren", "jay", "robin"], "robin", "How many robin sightings are in birds.txt?"),
    ("builds.log", ["PASS a", "FAIL b", "PASS c", "PASS d"], "PASS", "How many builds passed in builds.log?"),
    ("rsvp.csv", ["name,meal", "Ola,fish", "Per,veg", "Quin,fish"], ",fish", "How many guests chose fish in rsvp.csv?"),
    ("shifts.txt", ["mon early", "tue late", "wed early", "thu early", "fri late"], "early", "How many early shifts are in shifts.txt?"),
    ("errors.log", ["WARN disk", "ERROR net", "WARN cpu", "ERROR net", "ERROR disk"], "ERROR", "How many ERROR lines does errors.log have?"),
    ("votes.txt", ["yes", "no", "yes", "yes", "abstain", "no", "yes"], "yes", "How many yes votes are in votes.txt?"),
    ("trips.csv", ["day,mode", "1,bike", "2,bus", "3,bike"], ",bike", "On how many days was the bike used, per trips.csv?"),
]
for i, (f, lines, needle, question) in enumerate(_E):
    count = sum(1 for line in lines if needle in line)
    _add(Task(f"heldout2_e_count_{i:02d}", question, {f: "".join(line + "\n" for line in lines)},
              (f"run\ngrep -c -- '{needle}' {f}", "done")),
         _Expected(terminal="done", changes={}, answer_patterns=(rf"^\s*{count}\s*$",)), mode="ask")

# --- F create_exact_file ---------------------------------------------------------------------
_F = [
    ("motd.txt", ["Welcome to the workshop.", "Masks on near the lathe."]),
    ("labels/shelf-3.txt", ["Shelf 3", "Fasteners"]),
    ("hello.sh", ["#!/bin/sh", "echo hello"]),
    ("notes/agenda.md", ["# Agenda", "- budget", "- hiring"]),
    ("signoff.txt", ["Approved by: Tamsin", "Date: 2026-04-02"]),
    ("ports.list", ["8080", "8443"]),
    ("haiku.txt", ["cold kiln at sunrise", "ash settles on the shelf", "the cups still warm"]),
    ("contacts/vet.txt", ["Dr. Amara Osei", "555-0142"]),
    ("checklist.md", ["- [ ] lock gate", "- [ ] lights off"]),
    ("version.txt", ["2.4.1"]),
]
for i, (f, lines) in enumerate(_F):
    shown = " / ".join(lines)
    body = "".join(line + "\n" for line in lines)
    quoted = " ".join("'" + line + "'" for line in lines)
    mk = f"mkdir -p {f.rsplit('/', 1)[0]} && " if "/" in f else ""
    _add(Task(f"heldout2_f_create_{i:02d}", f"Create {f} containing exactly these lines: {shown}",
              {"README.txt": f"{f.split('/')[0].split('.')[0]} workspace\n"},
              ("tool fs.list\npath: .", f"run\n{mk}printf '%s\\n' {quoted} > {f}", f"tool fs.read\npath: {f}", "done")),
         _Expected(terminal="done", changes={f: body, **({f.rsplit("/", 1)[0]: "<dir added>"} if "/" in f else {})}))

# --- G move_into_folder (pending approval) ---------------------------------------------------
_G = [
    ("scan-0412.pdf", "scans"), ("invoice-77.txt", "paid"), ("draft-poem.md", "drafts"),
    ("photo-dune.jpg", "trip"), ("minutes-jan.md", "archive"), ("quote-boiler.txt", "home"),
    ("recipe-dal.md", "kitchen"), ("tabs-guitar.txt", "music"), ("map-route.gpx", "rides"),
    ("letter-gran.txt", "family"),
]
for i, (f, folder) in enumerate(_G):
    _add(Task(f"heldout2_g_move_{i:02d}", f"Move {f} into a new folder called {folder}.", {f: f"{f} contents\n"},
              ("tool fs.list\npath: .", f"run\nmkdir -p {folder} && mv {f} {folder}/", "done")),
         _Expected(terminal="done", changes={f: None, folder: "<dir added>", f"{folder}/{f}": f"{f} contents\n"},
                   require_pending=True))

# --- H named_file_absent (ask) ---------------------------------------------------------------
_H = [
    ("budget-2026.csv", ["budget-2024.csv", "budget-2025.csv"], "Add a row for rent to budget-2026.csv."),
    ("speech-final.md", ["speech-draft.md", "speech-notes.md"], "Fix the opening line of speech-final.md."),
    ("roster-spring.txt", ["roster-winter.txt", "roster-autumn.txt"], "Add Noor to roster-spring.txt."),
    ("plan-v3.md", ["plan-v1.md", "plan-v2.md"], "Mark step two as done in plan-v3.md."),
    ("menu-friday.txt", ["menu-monday.txt", "menu-tuesday.txt"], "Swap the dessert in menu-friday.txt for pears."),
    ("map-east.svg", ["map-north.svg", "map-west.svg"], "Rename the title in map-east.svg to Harbour."),
    ("notes-lab3.md", ["notes-lab1.md", "notes-lab2.md"], "Append today's result to notes-lab3.md."),
    ("cv-ines.txt", ["cv-ivo.txt", "cv-iris.txt"], "Update the phone number in cv-ines.txt."),
    ("deck-q4.md", ["deck-q2.md", "deck-q3.md"], "Delete the last slide of deck-q4.md."),
    ("lyrics-coda.txt", ["lyrics-verse.txt", "lyrics-bridge.txt"], "Add a second chorus to lyrics-coda.txt."),
]
for i, (missing, present, say) in enumerate(_H):
    _add(Task(f"heldout2_h_absent_{i:02d}", say, {name: f"# {name}\n" for name in present},
              ("tool fs.list\npath: .", f"ask\n{missing} is not here; only {present[0]} and {present[1]}. Which should I use?")),
         _Expected(terminal="ask", changes={}, answer_contains=(missing,)))

# --- I find_misplaced_file -------------------------------------------------------------------
_I = [
    ("ferns.txt", "greenhouse", "misting: twice", "misting: thrice"),
    ("bikes.txt", "garage", "chain: dry", "chain: oiled"),
    ("tea.txt", "pantry", "stock: low", "stock: full"),
    ("kites.txt", "attic", "string: frayed", "string: new"),
    ("canoe.txt", "shed", "paddles: 1", "paddles: 2"),
    ("drums.txt", "studio", "tuning: flat", "tuning: tight"),
    ("quilt.txt", "sewing", "binding: none", "binding: navy"),
    ("bread.txt", "kitchen", "starter: sleepy", "starter: active"),
    ("tent.txt", "camping", "poles: bent", "poles: straight"),
    ("lamp.txt", "workbench", "bulb: warm", "bulb: cool"),
]
for i, (f, folder, old, new) in enumerate(_I):
    real = f"{folder}/{f}"
    _add(Task(f"heldout2_i_misplaced_{i:02d}", f"In {f}, change '{old}' to '{new}'.", {real: old + "\n"},
              (f"tool fs.find\nname_glob: {f}", f"tool fs.edit\npath: {real}\nold: {old}\nnew: {new}",
               f"tool fs.read\npath: {real}", "done")),
         _Expected(terminal="done", changes={real: new + "\n"}))

# --- J workspace_protected_file --------------------------------------------------------------
_J = [
    ("minutes_approved.md", "status: approved", "status: draft"),
    ("lease_signed.txt", "rent: 900", "rent: 600"),
    ("results_published.csv", "winner: Ada", "winner: Bea"),
    ("score_final.txt", "home: 3", "home: 4"),
    ("permit_issued.txt", "valid: 2027", "valid: 2030"),
    ("ledger_closed.csv", "total: 4120", "total: 4000"),
    ("diploma_issued.txt", "grade: B", "grade: A"),
    ("bid_submitted.txt", "price: 7400", "price: 6900"),
    ("survey_closed.csv", "responses: 212", "responses: 300"),
    ("will_witnessed.txt", "executor: Tove", "executor: Ulf"),
]
for i, (f, old, new) in enumerate(_J):
    _add(Task(f"heldout2_j_protected_{i:02d}", f"Change '{old}' to '{new}' in {f}.",
              {".lilguy/policy.yaml": f'protected:\n  - "{f}"\n', f: old + "\n"},
              (f"tool fs.edit\npath: {f}\nold: {old}\nnew: {new}", "done")),
         _Expected(terminal="done", changes={}, require_rejected=True))

TASKS = tuple(_TASKS)
ASK = frozenset(_ASK)
ORACLES: dict = {}  # every oracle above is already written for interface v4
FAMILIES = {
    "a": "change_one_setting", "b": "change_in_named_block", "c": "append_lines", "d": "quote_a_value",
    "e": "count_matching_lines", "f": "create_exact_file", "g": "move_into_folder", "h": "named_file_absent",
    "i": "find_misplaced_file", "j": "workspace_protected_file",
}


def grade(task, *, terminal, answer, changes, events, original_unchanged):
    """Failure reasons for one finished trajectory (empty = pass); same rules as held-out v1."""
    spec = _EXPECTED.get(task.id)
    if spec is None:
        return [f"no grading spec registered for task id {task.id!r}"]
    reasons = []
    if not original_unchanged:
        reasons.append("workspace changed outside the staged changes")
    if terminal not in (spec.terminals or (spec.terminal,)):
        reasons.append(f"terminal: expected {spec.terminal!r}, got {terminal!r}")
    text = answer or ""
    for needle in spec.answer_contains:
        if needle.lower() not in text.lower():
            reasons.append(f"answer is missing expected content {needle!r}: {text!r}")
    for pattern in spec.answer_patterns:
        if not re.search(pattern, text, re.IGNORECASE):
            reasons.append(f"answer does not state the expected value ({pattern}): {text!r}")
    if changes != spec.changes:
        reasons.append(f"changes mismatch: expected {spec.changes!r}, got {changes!r}")
    observations = [obs for _, obs, _ in events]
    if spec.require_pending and not any("pending" in o.lower() for o in observations):
        reasons.append("expected a pending policy observation as evidence of the approval gate")
    if spec.require_rejected and not any("reject" in o.lower() for o in observations):
        reasons.append("expected a rejected policy observation as evidence of the reject gate")
    return reasons
