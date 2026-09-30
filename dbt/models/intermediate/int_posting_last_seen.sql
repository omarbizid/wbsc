-- When each posting was last observed (reportable observations only).
select
    o.posting_id,
    p.source_id,
    p.scope_key,
    min(o.observed_at) as first_seen_at,
    max(o.observed_at) as last_seen_at,
    max(b.started_at) as last_seen_batch_started_at,
    count(*) as n_observations,
    count(distinct o.version_id) as n_versions
from {{ ref('stg_observations') }} o
join {{ ref('stg_batches') }} b using (batch_id)
join {{ ref('stg_postings') }} p using (posting_id)
group by o.posting_id, p.source_id, p.scope_key
