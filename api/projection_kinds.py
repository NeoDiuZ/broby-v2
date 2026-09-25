"""PMS record kinds consumed by the typed clinical projection."""

PROJECTED_RECORD_KINDS = (
    'clinic', 'owner', 'patient', 'member', 'source', 'intake',
    'attachment', 'event', 'observation',
)

# All values are fixed source constants, never request or database input.
PROJECTED_KIND_SQL = '(' + ','.join("'" + kind + "'" for kind in PROJECTED_RECORD_KINDS) + ')'
