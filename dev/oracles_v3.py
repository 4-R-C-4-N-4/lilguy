"""Interface-v3 oracles for development questions: the last command prints the answer.

In v3 the answer to a question is the quoted output of the model's last command, so a scripted
solution must end with a command whose output alone answers the request. The v2 oracles stay in
their task modules unchanged (earlier versions remain reproducible); this table replaces them
only when evaluating v3. Lines use the same v2 action syntax as the task modules; a final `done`
is replayed bare. Development tasks only, never held-out.
"""

# Questions: issued with `lilguy ask` (read-only). The two conditional change requests whose
# scripted solution happens to change nothing (leave_matching_output_style,
# withhold_copy_when_only_prefix_matches) stay `do`: that is how a user would issue them.
ASK = frozenset({
    'read_only_question', 'aggregate_signed_amounts', 'compare_file_sizes_answer',
    'compare_preserved_record_bytes', 'compute_inventory_level_over_default',
    'copy_mode_without_executable_bit', 'count_lines_total', 'count_matching_rows',
    'detect_absent_final_line_feed', 'find_todo_comments', 'hidden_theme_lookup', 'latest_iso_timestamp',
    'leave_missing_notice_alone', 'matching_normalized_addresses', 'no_marker_in_schedule',
    'reconcile_manifest_versions', 'recover_export_owner_lookup', 'report_largest_measured_document',
    'report_tab_stop_from_specific_profile', 'summarize_missing_packet_ids', 'utf8_line_count'})

ORACLES = {
    'read_only_question': (
        "run\ngrep '^retry=' cfg/app.ini",
        'done'),
    'count_lines_total': (
        'run\nwc -l < access.log',
        'done'),
    'count_matching_rows': (
        "run\ngrep -c ',pending$' orders.csv",
        'done'),
    'find_todo_comments': (
        'run\ngrep -l TODO a.py b.py',
        'done'),
    'compare_file_sizes_answer': (
        'run\nwc -c small.txt big.txt',
        'run\necho "big.txt is larger by $(( $(wc -c < big.txt) - $(wc -c < small.txt) )) bytes"',
        'done'),
    'compute_inventory_level_over_default': (
        "run\ngrep '^stockroom_colour=' inventory.conf || grep '^default_colour=' inventory.conf",
        'done'),
    'matching_normalized_addresses': (
        "run\ndiff <(sed 's/[[:space:]]*$//' postcard-a.txt) <(sed 's/[[:space:]]*$//' postcard-b.txt)"
        " && echo same || echo differ",
        'done'),
    'no_marker_in_schedule': (
        'tool fs.read\npath: rota.txt',
        "run\ngrep -q '^CANCELLED[[:space:]]' rota.txt && echo 'yes, a CANCELLED row' || echo 'no CANCELLED row'",
        'done'),
    'leave_matching_output_style': (
        'tool fs.read\npath: display.ini',
        "run\ngrep -qx 'output_style=compact' display.ini && echo 'output_style is already compact, unchanged'",
        'done'),
    'leave_missing_notice_alone': (
        'tool fs.list\npath: .',
        "run\n[ -e yesterday.notice ] && head -n 1 yesterday.notice || echo 'yesterday.notice is absent'",
        'done'),
    'reconcile_manifest_versions': (
        'tool fs.read\npath: published/manifest.ini',
        'tool fs.read\npath: draft/manifest.ini',
        "run\np=$(sed -n 's/^label=//p' published/manifest.ini); d=$(sed -n 's/^label=//p' draft/manifest.ini)\n"
        'echo "published $p, draft $d"; [ "$p" = "$d" ] && echo agree || echo differ',
        'done'),
    'copy_mode_without_executable_bit': (
        'run\nstat -c %a -- run-notes.sh',
        "run\nfind run-notes.sh -perm /111 | grep -q . && echo executable || echo 'not executable'",
        'done'),
    'withhold_copy_when_only_prefix_matches': (
        'tool fs.read\npath: status.flag',
        "run\ngrep -qx READY status.flag && cp docket.txt review-drop/docket.txt"
        " || echo 'not copied: no line is exactly READY'",
        'done'),
    'detect_absent_final_line_feed': (
        'run\ntail -c 1 -- alphabet-snippet.txt | od -An -c',
        'run\ntail -c 1 alphabet-snippet.txt | od -An -c; '
        "[ -n \"$(tail -c 1 alphabet-snippet.txt)\" ] && echo 'no final LF' || echo 'ends with LF'",
        'done'),
    'compare_preserved_record_bytes': (
        'run\ndiff old/west-ticket.txt new/west-ticket.txt; [ "$?" -eq 1 ]',
        'run\ncmp -s old/west-ticket.txt new/west-ticket.txt && echo identical || echo differ',
        'done'),
    'report_tab_stop_from_specific_profile': (
        'tool fs.read\npath: format.conf',
        "run\nsed -n '/^\\[print\\]/,/^\\[/p' format.conf | grep '^tabstop='",
        'done'),
    'recover_export_owner_lookup': (
        'tool fs.read\npath: owners/active.txt',
        'tool fs.read\npath: owners/last-known.txt',
        "run\ngrep '^duty_owner:' owners/last-known.txt",
        'done'),
    'report_largest_measured_document': (
        'run\nwc -c -- dispatch/*.note',
        "run\nwc -c dispatch/*.note | grep -v ' total$' | sort -n | tail -n 1",
        'done'),
}
