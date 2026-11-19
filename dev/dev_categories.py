"""Roadmap categories for every development task (Fast12 and the broad batches).

Used only to report development pass rates per category; never consulted for training data.
"""
CATEGORIES = ('inspect', 'read-only', 'edit', 'organise', 'delete', 'permissions', 'archives', 'scripts',
              'ask', 'recovery')

_BY_CATEGORY = {
    'inspect': ('count_lines_total', 'count_matching_rows', 'find_todo_comments', 'compare_file_sizes_answer',
                'utf8_line_count', 'aggregate_signed_amounts', 'matching_normalized_addresses',
                'latest_iso_timestamp', 'summarize_missing_packet_ids', 'detect_absent_final_line_feed',
                'report_largest_measured_document', 'compare_preserved_record_bytes'),
    'read-only': ('read_only_question', 'hidden_theme_lookup', 'no_marker_in_schedule', 'leave_missing_notice_alone',
                  'reconcile_manifest_versions', 'report_tab_stop_from_specific_profile',
                  'compute_inventory_level_over_default'),
    'edit': ('rename_status_flag', 'bump_version_two_files', 'named_config_specific', 'create_new_file',
             'exact_match_required_edit', 'extract_email_column', 'extract_first_field_space_separated',
             'find_lines_with_error', 'sort_numbers_ascending', 'sort_names_reverse', 'diff_two_lists_added',
             'quoted_label_index', 'middle_excerpt', 'guide_selected_input', 'literal_marker_filter',
             'merge_pages_in_named_order', 'csv_quoted_location_values', 'project_priority_status_json',
             'windows_line_endings_copy', 'sum_inventory_per_bin', 'pair_audio_ids_to_titles',
             'files_with_dash_prefix', 'leave_matching_output_style', 'update_only_section_match',
             'format_tabular_missing_weights', 'append_absent_inventory_entry', 'extract_shared_playlist_ids',
             'extract_actual_uncommented_identifiers', 'insert_line_at_changelog_heading',
             'filter_capacity_at_inclusive_limit', 'replace_metacharacter_text_literally',
             'prepare_markdown_package_manifest'),
    'organise': ('organize_logs_into_dir', 'archive_old_report', 'move_closed_batch_pending',
                 'move_print_spool_within_build', 'copy_review_folder_structure', 'prepare_named_drop_folders',
                 'archive_if_ready_marker_matches', 'withhold_copy_when_only_prefix_matches',
                 'preserve_dotfile_during_backup'),
    'delete': ('pending_delete_requires_approval', 'delete_build_artifact_auto_ok'),
    'permissions': ('rejected_protected_file', 'restrict_local_draft_mode', 'executable_tools_group_pending',
                    'copy_mode_without_executable_bit'),
    'archives': (),
    'scripts': ('generate_tuple_named_notes', 'repair_unclosed_shell_branch', 'emit_literal_print_script'),
    'ask': ('ambiguous_config_pair', 'ambiguous_general_target', 'choose_language_edition',
            'clarify_missing_recording_order', 'resolve_conflicting_separator_guides', 'ask_filename_date_convention',
            'ask_which_print_run_quantity', 'find_copy_collision_before_replace', 'clarify_duplicate_current_revision'),
    'recovery': ('recovery_after_typo', 'recover_export_owner_lookup'),
}

CATEGORY = {task: category for category, tasks in _BY_CATEGORY.items() for task in tasks}


def category(task_id):
    try:
        return CATEGORY[task_id]
    except KeyError:
        raise KeyError(f'development task {task_id!r} has no category; add it to dev/dev_categories.py') from None
