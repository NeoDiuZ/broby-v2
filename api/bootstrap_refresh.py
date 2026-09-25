"""Conditional workspace reads; tokens never substitute for live authorization.

Only the PMS record payload is skipped. Native clinical rows and the small live
metadata response are still read on every poll. Reconciliation dependencies span
clinics and stores, so any review disables this shortcut deployment-wide.
"""
import hashlib
import json
import re
import uuid

BOOT_ID = uuid.uuid4().hex


def setup(c):
    # Empty on installation, including before a verified SQLite -> PG promotion.
    # Existing rows get a full first response; subsequent writes advance revision.
    c.execute('CREATE TABLE IF NOT EXISTS bootstrap_revisions(clinic_id TEXT PRIMARY KEY, revision BIGINT NOT NULL)')
    c.execute('CREATE INDEX IF NOT EXISTS records_bootstrap_kind ON records(kind)')
    if c.dialect == 'postgres':
        c.executescript('''
        CREATE OR REPLACE FUNCTION advance_bootstrap_revision() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP <> 'INSERT' THEN
            INSERT INTO bootstrap_revisions VALUES(OLD.clinic_id,1)
              ON CONFLICT(clinic_id) DO UPDATE SET revision=bootstrap_revisions.revision+1;
          END IF;
          IF TG_OP = 'INSERT' OR (TG_OP = 'UPDATE' AND NEW.clinic_id <> OLD.clinic_id) THEN
            INSERT INTO bootstrap_revisions VALUES(NEW.clinic_id,1)
              ON CONFLICT(clinic_id) DO UPDATE SET revision=bootstrap_revisions.revision+1;
          END IF;
          IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
          RETURN NEW;
        END;
        $$;
        CREATE OR REPLACE TRIGGER bootstrap_records AFTER INSERT OR UPDATE OR DELETE ON records
          FOR EACH ROW EXECUTE FUNCTION advance_bootstrap_revision();
        ''')
    else:
        for name, operation, condition, reference in (
            ('insert', 'INSERT', '', 'NEW'),
            ('update', 'UPDATE', '', 'OLD'),
            ('move', 'UPDATE', 'WHEN NEW.clinic_id <> OLD.clinic_id', 'NEW'),
            ('delete', 'DELETE', '', 'OLD'),
        ):
            c.execute(f'''CREATE TRIGGER IF NOT EXISTS bootstrap_records_{name}
              AFTER {operation} ON records {condition} BEGIN
              INSERT INTO bootstrap_revisions VALUES({reference}.clinic_id,1)
              ON CONFLICT(clinic_id) DO UPDATE SET revision=revision+1; END''')


def conditional(c, request, clinic, actor, metadata, native):
    """Call within the same repeatable read as metadata and full PMS records.

    The boot identifier invalidates clients after restart/restore. Different API
    processes can cause additional full reads, never reuse another process's
    stale snapshot. This is not a multi-replica caching claim.
    """
    revision = c.execute('SELECT revision FROM bootstrap_revisions WHERE clinic_id=?', (clinic,)).fetchone()
    # A retained original or onward transfer can change eligibility without a
    # local ledger write. No local revision claims to close that dependency graph.
    has_reviews = bool(c.execute("SELECT 1 FROM records WHERE kind='clinical_reconciliation_review' LIMIT 1").fetchone())
    metadata = dict(metadata)
    if 'clinical_verification' in metadata:
        # Verification time describes this read, not a change to its contents.
        # Reviews still force the full eligibility path regardless of this hash.
        metadata['clinical_verification'] = {key: value for key, value in metadata['clinical_verification'].items() if key != 'verified_at'}
    encoded = json.dumps({'format': 1, 'boot': BOOT_ID, 'clinic': clinic, 'actor': actor,
                          'revision': revision[0] if revision else 0,
                          'metadata': metadata, 'native': native}, sort_keys=True,
                         separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()
    token = hashlib.sha256(encoded).hexdigest()
    previous = request.query_params.get('since', '')
    unchanged = not has_reviews and bool(re.fullmatch('[a-f0-9]{64}', previous)) and previous == token
    return token, unchanged
