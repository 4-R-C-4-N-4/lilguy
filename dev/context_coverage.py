"""Context coverage counts used by the decision diagnosis (development-independent, corpus only).

* requests that name a file path absent from the initial workspace (a not-yet-existing output);
* the next-action targets that follow a not-found observation.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re

PATH = re.compile(r'[\w./-]+\.(?:txt|csv|md|ini|cfg|json|log|sh|yaml|tar)')
NOT_FOUND = re.compile(r'No such file|ENOENT|not found|does not exist|Expected a regular file|no matches', re.I)


def names_missing_path(request, files):
    """True when the request names a path that neither exists nor is the basename of one."""
    for name in PATH.findall(request):
        if name not in files and not any(path.endswith('/' + name) for path in files):
            return True
    return False


def after_not_found(rows):
    """First-line targets of rows whose preceding observation reports a missing path."""
    return Counter(r[-1]['content'].split('\n', 1)[0] for r in rows
                   if len(r) >= 4 and NOT_FOUND.search(r[-2]['content']))


def main(argv=None):
    parser = argparse.ArgumentParser(description='Context coverage counts for a built corpus v2 directory.')
    parser.add_argument('corpus', type=Path)
    args = parser.parse_args(argv)
    evidence = json.loads((args.corpus / 'effects.json').read_text())
    rows = [json.loads(line)['messages'] for line in (args.corpus / 'train.jsonl').read_text().splitlines()]
    probes = sum(any(t['action']['tool'] in ('fs.read', 'fs.find', 'fs.list') and t['observation'].startswith('exit=1')
                     for t in e['record']['turns'][:1]) for e in evidence)
    result = {'episodes': len(evidence),
              'requests_naming_missing_path': sum(names_missing_path(e['task']['request'], e['task']['files'])
                                                  for e in evidence),
              'targets_after_not_found': dict(after_not_found(rows).most_common()),
              'episodes_opening_with_failed_lookup': probes}
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
