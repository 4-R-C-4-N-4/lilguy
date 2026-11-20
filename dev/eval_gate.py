"""Verify an operator-pinned held-out manifest, without evaluating its tasks."""
import hashlib

from dev.split_audit import ManifestError, audit, parse_manifest


def verify(held_path, pin, candidate_path):
    def fail(reason):
        return {'ok': False, 'reason': reason}

    try:
        raw = held_path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != pin:
            return fail('held-out digest mismatch')
        held = parse_manifest(raw.decode('utf8'))
        if len(held) < 100 or any(e.split != 'held-out' for e in held):
            return fail('expected at least 100 held-out tasks')
        other = parse_manifest(candidate_path.read_text(encoding='utf8'))
        if any(e.split not in ('dev', 'train') for e in other):
            return fail('unexpected candidate split')
        rows = held + other
        if len({e.id for e in rows}) != len(rows) or any(not (e.template_id or '').strip() for e in rows):
            return fail('duplicate id or missing template id')
        # Fast12 deliberately pairs two requests and two fixtures. These exceptions
        # are field-specific and apply only to the exact two-member dev groups.
        recovery_pair = frozenset(('recovery_after_typo', 'rename_status_flag'))
        result = audit(rows, dev_request_pairs=[recovery_pair],
                       dev_fixture_pairs=[recovery_pair, frozenset(('staging_config_timeout', 'named_config_specific'))])
        if not result.ok:
            return fail('split audit detected overlap')
        return {'ok': True, 'held_out_count': len(held), 'candidate_count': len(other), 'held_out_sha256': pin}
    except (ManifestError, OSError, UnicodeError):
        return fail('unreadable or malformed manifest')
