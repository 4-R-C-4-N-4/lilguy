# Revision 9 development evidence

Paired result grid: columns are r7/42, r8/42, r7/43, r8/43; + pass, - miss. Same 80 tasks in all eight runs; no held-out inference. A pass is the frozen grader verdict, not independent semantic approval.

| Task | Category | MiniCPM | Qwen |
|---|---|---|---|
| aggregate_signed_amounts | inspect | ++-+ | ---- |
| append_absent_inventory_entry | edit | ++++ | --+- |
| append_meeting_agenda_item | explicit | ++++ | ++++ |
| archive_if_ready_marker_matches | organise | ++++ | ++++ |
| archive_old_report | organise | ++++ | ++++ |
| bump_version_two_files | edit | ---- | ---- |
| combine_lectures_b_then_a | explicit | ++-- | +-+- |
| compare_file_sizes_answer | inspect | ---- | ---- |
| compare_preserved_record_bytes | inspect | ---- | --+- |
| compute_inventory_level_over_default | read-only | -+-+ | -+-+ |
| copy_east_welcome_line | explicit | --++ | --++ |
| copy_english_edition | explicit | ++++ | ++-- |
| copy_mode_without_executable_bit | permissions | ---- | ---- |
| copy_review_folder_structure | organise | ---- | ---- |
| count_lines_total | inspect | ++++ | ++++ |
| count_matching_rows | inspect | +-++ | -+++ |
| create_new_file | edit | ++++ | ++++ |
| csv_quoted_location_values | edit | ---- | ---- |
| delete_build_artifact_auto_ok | delete | ++++ | ++++ |
| detect_absent_final_line_feed | inspect | ---+ | ---- |
| diff_two_lists_added | edit | ++++ | -+++ |
| emit_literal_print_script | scripts | ---- | ---- |
| exact_match_required_edit | edit | ++++ | ++-+ |
| executable_tools_group_pending | permissions | +++- | ---- |
| export_codes_with_print_separator | explicit | --+- | +--- |
| extract_actual_uncommented_identifiers | edit | ---- | ---- |
| extract_email_column | edit | ++++ | +--- |
| extract_first_field_space_separated | edit | ++++ | ++++ |
| extract_shared_playlist_ids | edit | ---- | ---- |
| files_with_dash_prefix | edit | ---- | ---- |
| filter_capacity_at_inclusive_limit | edit | ---- | ---- |
| find_lines_with_error | edit | +-++ | ---- |
| find_todo_comments | inspect | +++- | -++- |
| format_tabular_missing_weights | edit | +--- | ---- |
| generate_tuple_named_notes | scripts | +--- | ---- |
| guide_selected_input | edit | ---- | ---- |
| hidden_theme_lookup | read-only | ++-+ | ---- |
| insert_line_at_changelog_heading | edit | ---- | ---- |
| latest_iso_timestamp | inspect | -++- | +++- |
| leave_matching_output_style | edit | -+-+ | -+-+ |
| leave_missing_notice_alone | read-only | ---- | ---- |
| literal_marker_filter | edit | ---- | ---- |
| matching_normalized_addresses | inspect | -+-+ | ---- |
| merge_pages_in_named_order | edit | ++++ | ++++ |
| middle_excerpt | edit | ++++ | +-++ |
| move_closed_batch_pending | organise | ++++ | ---- |
| move_print_spool_within_build | organise | ++++ | ++++ |
| named_config_specific | edit | ++++ | ++++ |
| night_order_quantity | explicit | ++++ | ++++ |
| no_marker_in_schedule | read-only | ++-+ | +--+ |
| organize_logs_into_dir | organise | ++++ | ++++ |
| pair_audio_ids_to_titles | edit | ---- | ---- |
| pending_delete_requires_approval | delete | ++++ | ++++ |
| prepare_markdown_package_manifest | edit | ---- | ---- |
| prepare_named_drop_folders | organise | ++++ | ++++ |
| preserve_dotfile_during_backup | organise | ++-- | ---+ |
| project_priority_status_json | edit | ---- | ---- |
| quoted_label_index | edit | ---- | ---- |
| read_only_question | read-only | -+++ | ++++ |
| reconcile_manifest_versions | read-only | ---- | ---- |
| recover_export_owner_lookup | recovery | ---- | -+-+ |
| recovery_after_typo | recovery | ++++ | ++++ |
| rejected_protected_file | permissions | ++++ | ++++ |
| rename_status_flag | edit | ++++ | ++++ |
| repair_unclosed_shell_branch | scripts | ---- | ---- |
| replace_metacharacter_text_literally | edit | ---+ | ---- |
| replace_release_cover | explicit | ++++ | ++++ |
| report_largest_measured_document | inspect | ++++ | -+++ |
| report_tab_stop_from_specific_profile | read-only | ---- | -+-+ |
| restrict_local_draft_mode | permissions | ++++ | ++++ |
| scan_date_month_first | explicit | ++++ | ++-+ |
| sort_names_reverse | edit | +-++ | ++++ |
| sort_numbers_ascending | edit | ++++ | ++++ |
| staging_config_timeout | explicit | ++++ | ++++ |
| sum_inventory_per_bin | edit | ---- | ---- |
| summarize_missing_packet_ids | inspect | ++++ | --++ |
| update_only_section_match | edit | ---- | ---- |
| utf8_line_count | inspect | ++++ | ++-- |
| windows_line_endings_copy | edit | +-++ | ++++ |
| withhold_copy_when_only_prefix_matches | organise | +--- | ---- |

## R8 seed 42: 32 shared successes
MiniCPM only: aggregate_signed_amounts, append_absent_inventory_entry, combine_lectures_b_then_a, executable_tools_group_pending, extract_email_column, hidden_theme_lookup, matching_normalized_addresses, middle_excerpt, move_closed_batch_pending, no_marker_in_schedule, preserve_dotfile_during_backup, summarize_missing_packet_ids
Qwen only: count_matching_rows, recover_export_owner_lookup, report_tab_stop_from_specific_profile, sort_names_reverse, windows_line_endings_copy
minicpm, medians on the same 32 successful tasks (seconds): model_seconds 0.167, episode_seconds 0.838
qwen08, medians on the same 32 successful tasks (seconds): model_seconds 0.189, episode_seconds 0.886

## R8 seed 43: 35 shared successes
MiniCPM only: aggregate_signed_amounts, append_absent_inventory_entry, copy_english_edition, detect_absent_final_line_feed, extract_email_column, find_lines_with_error, hidden_theme_lookup, matching_normalized_addresses, move_closed_batch_pending, replace_metacharacter_text_literally, utf8_line_count
Qwen only: preserve_dotfile_during_backup, recover_export_owner_lookup, report_tab_stop_from_specific_profile
minicpm, medians on the same 35 successful tasks (seconds): model_seconds 0.184, episode_seconds 0.920
qwen08, medians on the same 35 successful tasks (seconds): model_seconds 0.185, episode_seconds 0.886

## Script audit: terminal, effects, failures and action sequence (all 24 traces)

### emit_literal_print_script
- pilot-i99_qvnk/minicpm: budget; staged: []; expected done, staged effects differ from expected output. fs.list → exit=0; printf '%s\n' '#!/bin/sh' && printf '%s\n' "printf '%s\n' '$STAGE'" → exit=0; fs.edit → exit=1; fs.find → exit=0; fs.edit → exit=1; fs.list → exit=0
- pilot-i99_qvnk/qwen08: done; staged: []; staged effects differ from expected output, no successful final tool step. fs.list → exit=0; printf '%s\n' '#!/bin/sh' 'printf '%s\n' '$STAGE' > show-marker.sh → exit=2; fs.read → exit=1
- pilot-vkuaegj1/minicpm: done; staged: ['show-marker.sh']; staged effects differ from expected output. fs.list → exit=0; printf '%s\n' '#!/bin/sh' && printf '%s\n' '$STAGE' > show-marker.sh → exit=0
- pilot-vkuaegj1/qwen08: done; staged: ['show-marker.sh']; staged effects differ from expected output. fs.read → exit=1; fs.find → exit=0; fs.list → exit=0; printf '%s\n' '#!/bin/sh' && printf '%s\n' '$STAGE' > show-marker.sh → exit=0
- pilot-p9tcy7s0/control/minicpm: done; staged: ['show-marker.sh']; staged effects differ from expected output. fs.list → exit=0; printf '%s\n' '#!/bin/sh' && printf '%s\n' 'printf \'%s\\n\' \'$STAGE\'' > show-marker.sh → exit=2; printf '%s\n' '#!/bin/sh' && printf '%s\n' 'printf "%s\n" "$STAGE"' > show-marker.sh → exit=0
- pilot-p9tcy7s0/control/qwen08: budget; staged: []; expected done, staged effects differ from expected output. fs.read → exit=1; fs.find → exit=0; fs.list → exit=0; printf '%s\n' '#!/bin/sh' 'printf '%s\n' '$STAGE' → exit=2; fs.read → exit=1; fs.find → exit=0
- pilot-p9tcy7s0/treatment/minicpm: budget; staged: []; expected done, staged effects differ from expected output, no successful final tool step. fs.list → exit=0; printf '%s\n' '#!/bin/sh\nprintf \'%s\\n\' \'$STAGE\'' > show-marker.sh → exit=2; printf '%s\n' '#!/bin/sh\nprintf \'%s\n\' \'$STAGE\'' > show-marker.sh → exit=2; fs.read → exit=1; fs.list → exit=0; printf '%s\n' '#!/bin/sh\nprintf \'%s\n\' \'$STAGE\'' > show-marker.sh → exit=2
- pilot-p9tcy7s0/treatment/qwen08: done; staged: []; staged effects differ from expected output, no successful final tool step. fs.read → exit=1; fs.list → exit=0; fs.edit → exit=1

### generate_tuple_named_notes
- pilot-i99_qvnk/minicpm: done; staged: ['queue/atlas.note', 'queue/beacon.note']; pass. fs.read → exit=0; fs.list → exit=0; while IFS=$'\t' read -r key val; do echo "$val" > "queue/$key"; done < mapping.tsv → exit=0; fs.read → exit=0; fs.read → exit=0
- pilot-i99_qvnk/qwen08: done; staged: ['queue/readme.txt']; staged effects differ from expected output. fs.list → exit=0; cut -d, -f2 mapping.tsv > queue/readme.txt → exit=0
- pilot-vkuaegj1/minicpm: budget; staged: []; expected done, staged effects differ from expected output, no successful final tool step. fs.list → exit=0; fs.read → exit=0; mkdir -p queue && while IFS=$'\t' read -r first second; do echo "$second"$'\n'; done < mapping.tsv > queue/$(echo "$first" | tr -d '\n') → exit=1 tags=EISDIR(queue/); fs.list → exit=0; mkdir -p queue && while IFS=$'\t' read -r first second; do echo "$second"$'\n'; done < mapping.tsv > queue/$(echo "$first" | tr -d '\n') → exit=1 tags=EISDIR(queue/); mkdir -p queue && while IFS=$'\t' read -r first second; do echo "$second"$'\n'; done < mapping.tsv > queue/$(echo "$first" | tr -d '\n') → exit=1 tags=EISDIR(queue/)
- pilot-vkuaegj1/qwen08: done; staged: ['queue/second_col.txt']; staged effects differ from expected output. fs.list → exit=0; cut -d' ' -f2- queue/readme.txt > queue/second_col.txt → exit=0; fs.read → exit=0
- pilot-p9tcy7s0/control/minicpm: done; staged: ['queue/North pier', 'queue/West field']; staged effects differ from expected output. fs.read → exit=0; mkdir -p queue && awk -F'\t' '{printf "%s\n", $2}' mapping.tsv | while IFS= read -r line; do echo "$line" > "queue/$line"; done → exit=0; fs.list → exit=0
- pilot-p9tcy7s0/control/qwen08: done; staged: []; staged effects differ from expected output. fs.list → exit=0; cut -d, -- 'queue/' column2 mapping.tsv > queue/$(cut -d, -- 'queue/' column2 mapping.tsv | head -n 1) → exit=1 tags=EISDIR(queue/),USAGE; fs.find → exit=0; fs.list → exit=0; fs.read → exit=0
- pilot-p9tcy7s0/treatment/minicpm: done; staged: ['queue/beacon.note', 'queue/readme.txt']; staged effects differ from expected output. fs.read → exit=0; mkdir -p queue && cat mapping.tsv | cut -f2 > queue/* → exit=0; fs.list → exit=0; fs.read → exit=0; : > queue/beacon.note → exit=0
- pilot-p9tcy7s0/treatment/qwen08: done; staged: ['queue/first.txt']; staged effects differ from expected output. fs.read → exit=0; printf '%s\n' atlas.note beacon.note > queue/first.txt → exit=0

### repair_unclosed_shell_branch
- pilot-i99_qvnk/minicpm: done; staged: []; staged effects differ from expected output. fs.read → exit=0; bash -n preview-note.sh → exit=2 tags=SYNTAX; fs.edit → exit=0
- pilot-i99_qvnk/qwen08: done; staged: []; staged effects differ from expected output. fs.read → exit=0; sed -i 's/printf "%s\n"/printf "%s"/' preview-note.sh → exit=0
- pilot-vkuaegj1/minicpm: done; staged: ['preview-note.sh']; staged effects differ from expected output. fs.read → exit=0; bash -n preview-note.sh → exit=2 tags=SYNTAX; fs.edit → exit=0; bash -n preview-note.sh → exit=0
- pilot-vkuaegj1/qwen08: done; staged: []; staged effects differ from expected output, no successful final tool step. fs.read → exit=0; grep -qx '}' preview-note.sh && echo 'syntax ok; no missing closing ' → exit=1
- pilot-p9tcy7s0/control/minicpm: budget; staged: ['preview-note.sh']; expected done, staged effects differ from expected output, no successful final tool step. fs.read → exit=0; fs.edit → exit=0; bash -n preview-note.sh → exit=2 tags=SYNTAX; fs.edit → exit=1; fs.read → exit=0; bash -n preview-note.sh → exit=2 tags=SYNTAX
- pilot-p9tcy7s0/control/qwen08: done; staged: ['preview-note.sh']; staged effects differ from expected output. fs.read → exit=0; sed -i '/^if test -f notice.txt;/a\  fi' preview-note.sh → exit=0; fs.read → exit=0
- pilot-p9tcy7s0/treatment/minicpm: done; staged: ['preview-note.sh']; staged effects differ from expected output. fs.read → exit=0; fs.edit → exit=0
- pilot-p9tcy7s0/treatment/qwen08: done; staged: []; staged effects differ from expected output. fs.read → exit=0; tail -n +2 preview-note.sh | grep -v '^$' → exit=0

## Historical wrong answers: all 19 agent-audited cases
Each line gives the earlier agent finding, followed by r8 grader outcomes on seeds 42 and 43 for the same base. A grader pass does not prove every semantic issue is fixed.
- minicpm / compare_preserved_record_bytes: The files differ, but new/west-ticket.txt is 12 bytes and one byte shorter. Only the old file ends with a newline. R8: miss, miss
- minicpm / copy_mode_without_executable_bit: The conclusion that nobody can execute the file is correct. The claim that the owner has the execute bit is false because all three execute positions are unset. R8: miss, miss
- minicpm / detect_absent_final_line_feed: The last byte is Z, so the answer to whether the file ends with LF is no. R8: miss, pass
- minicpm / filter_capacity_at_inclusive_limit: Both qualifying rooms are present in the answer, but the order is reversed and capacities were included. The requested result is Swift followed by Finch, with names only. The model printed rows and staged no file. R8: miss, miss
- minicpm / reconcile_manifest_versions: The model substitutes the directory names for the release labels. The published label is amber-16 and the draft label is amber-61. Its conclusion that they differ is correct. R8: miss, miss
- minicpm / summarize_missing_packet_ids: q709 and q101 appear in requested.ids and are absent from received.ids. The answer falsely claims every requested ID was received. R8: pass, pass
- qwen08 / bump_version_two_files: The answer claims package.json was updated, but the read after the attempted edit still shows version 1.0.0. R8: miss, miss
- qwen08 / aggregate_signed_amounts: The signed amounts sum to 11. The reported 0 came from summing an empty second field. R8: miss, miss
- qwen08 / compare_preserved_record_bytes: The files do differ, but the asserted two-byte difference in Row H is false. The only differing byte is the final LF in the old file. R8: miss, miss
- qwen08 / compute_inventory_level_over_default: The inventory default is overridden by stockroom_colour=indigo in inventory.conf. A separate stockroom.cfg is unnecessary. R8: pass, pass
- qwen08 / copy_mode_without_executable_bit: The packet's reference stat measured mode 644, which has no execute bits. The model's listing showed a regular file and byte size, and supplies neither ownership nor mode evidence for its affirmative answer. R8: miss, miss
- qwen08 / detect_absent_final_line_feed: The fixture ends in Z (0x5A) and has no final LF (0x0A). The observed octal value is the ending offset. R8: miss, miss
- qwen08 / files_with_dash_prefix: The claimed copy did not happen. The copy command rejected the dash-prefixed operand as an option, staged nothing, and the destination read failed. R8: miss, miss
- qwen08 / find_todo_comments: The answer correctly counts one TODO in b.py but falsely counts two in a.py, which has zero. R8: pass, miss
- qwen08 / latest_iso_timestamp: The latest time is correctly stated, but the 10:24Z row belongs to sparrow. Finch recorded 10:20Z. R8: pass, miss
- qwen08 / matching_normalized_addresses: Both original files have the same two lines after trailing spaces and the trailing tab are removed. The diff marker 2c2 is not file content. R8: miss, miss
- qwen08 / report_largest_measured_document: The stated size for coast.note is correct, but inland.note is larger at 13 bytes. R8: pass, pass
- qwen08 / summarize_missing_packet_ids: The missing requested IDs are q101 and q709. The answer also includes q205, which was received, and q363, which was received and never requested. R8: miss, pass
- qwen08 / utf8_line_count: The requested non-empty count is three. The answer instead states that three lines contain no spaces. All four physical lines contain no spaces, including the blank line. R8: pass, miss
