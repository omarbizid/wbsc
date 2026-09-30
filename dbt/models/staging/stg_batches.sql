select
    batch_id,
    source_id,
    started_at,
    finished_at,
    status,
    n_items,
    n_failed_items,
    error,
    is_synthetic
from {{ source('ops', 'collection_batch') }}
{% if not var('include_synthetic') %}
where not is_synthetic
{% endif %}
