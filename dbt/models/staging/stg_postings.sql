select
    posting_id,
    source_id,
    source_job_id,
    scope_key,
    first_seen_at,
    last_seen_at
from {{ source('core', 'posting') }}
