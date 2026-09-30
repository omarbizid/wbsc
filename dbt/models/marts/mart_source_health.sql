-- Freshness and reliability per source (one row per registered source).
with last_batch as (
    select distinct on (source_id) source_id, batch_id, started_at, status, error,
           n_items, n_failed_items
    from {{ ref('stg_batches') }}
    order by source_id, started_at desc
),

last_success as (
    select source_id, max(started_at) as last_success_at
    from {{ ref('stg_batches') }}
    where status in ('success', 'partial')
    group by source_id
),

recent as (
    select source_id,
           count(*) filter (where status = 'failed') as failed_batches_7d,
           count(*) as batches_7d
    from {{ ref('stg_batches') }}
    where started_at > now() - interval '7 days'
    group by source_id
),

quarantine as (
    select source_id, count(*) as open_quarantine
    from {{ ref('stg_quarantine') }}
    where is_open
    group by source_id
),

postings as (
    select source_id,
           count(*) filter (where is_active) as active_postings,
           count(*) as total_postings
    from {{ ref('dim_postings') }}
    group by source_id
)

select
    s.source_id,
    s.display_name,
    s.method,
    lb.started_at as last_batch_at,
    lb.status as last_batch_status,
    lb.error as last_batch_error,
    lb.n_items as last_batch_items,
    lb.n_failed_items as last_batch_failed_items,
    ls.last_success_at,
    round(extract(epoch from now() - ls.last_success_at)::numeric / 3600, 1) as hours_since_success,
    ls.last_success_at is null
        or ls.last_success_at < now() - interval '{{ var("stale_after_hours") }} hours' as is_stale,
    coalesce(r.failed_batches_7d, 0) as failed_batches_7d,
    coalesce(r.batches_7d, 0) as batches_7d,
    coalesce(q.open_quarantine, 0) as open_quarantine,
    coalesce(p.active_postings, 0) as active_postings,
    coalesce(p.total_postings, 0) as total_postings,
    now() as marts_built_at
from {{ source('ops', 'source') }} s
left join last_batch lb using (source_id)
left join last_success ls using (source_id)
left join recent r using (source_id)
left join quarantine q using (source_id)
left join postings p using (source_id)
