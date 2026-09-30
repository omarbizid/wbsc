select
    quarantine_id,
    batch_id,
    source_id,
    record_key,
    reason,
    details,
    raw_ref,
    parser_version,
    first_seen_at,
    last_seen_at,
    resolved_at,
    resolved_at is null as is_open
from {{ source('ops', 'quarantine') }}
