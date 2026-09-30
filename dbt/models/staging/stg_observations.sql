-- Only observations from batches that count for reporting (synthetic excluded unless enabled).
select
    o.posting_id,
    o.batch_id,
    o.version_id,
    o.observed_at,
    b.source_id,
    b.is_synthetic
from {{ source('core', 'posting_observation') }} o
join {{ source('ops', 'collection_batch') }} b using (batch_id)
{% if not var('include_synthetic') %}
where not b.is_synthetic
{% endif %}
