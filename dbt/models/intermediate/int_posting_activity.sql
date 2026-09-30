-- Active / inactive status.
--
-- Rule: a posting is INACTIVE once it has been absent from
-- var('inactive_after_missed_batches') consecutive SUCCESSFUL collections of its scope
-- (same source and same board / company / search query) after it was last seen.
-- Collections of the scope that failed are ignored: a failed source never makes
-- postings look removed. Otherwise it is ACTIVE.
--
-- Retired scope: if the source kept running but no longer collects the posting's scope
-- at all (a board or search query removed from config/sources.yml), we can no longer
-- observe the posting. After the same number of source batches without the scope it is
-- flagged `scope_retired` and not counted as active (status unknown, not "removed").
with cur as (
    select posting_id, source_id, scope_key, last_seen_at, last_seen_batch_started_at
    from {{ ref('int_posting_last_seen') }}
),

missed as (
    select
        cur.posting_id,
        s.batch_started_at,
        row_number() over (partition by cur.posting_id order by s.batch_started_at) as n_missed
    from cur
    join {{ ref('stg_batch_scopes') }} s
        on s.source_id = cur.source_id
       and s.scope_key = cur.scope_key
       and s.scope_status = 'success'
       and s.batch_started_at > cur.last_seen_batch_started_at
),

source_batches as (
    select distinct source_id, batch_started_at from {{ ref('stg_batch_scopes') }}
),

retired as (
    -- later batches of the source that did not include the posting's scope at all
    select cur.posting_id, count(*) as n_batches_without_scope
    from cur
    join source_batches sb
        on sb.source_id = cur.source_id
       and sb.batch_started_at > cur.last_seen_batch_started_at
    where not exists (
        select 1 from {{ ref('stg_batch_scopes') }} s
        where s.source_id = cur.source_id
          and s.scope_key = cur.scope_key
          and s.batch_started_at = sb.batch_started_at
    )
    group by cur.posting_id
)

select
    cur.posting_id,
    coalesce(max(m.n_missed), 0) as n_successful_batches_missed,
    coalesce(max(r.n_batches_without_scope), 0)
        >= {{ var('inactive_after_missed_batches') }} as scope_retired,
    coalesce(max(m.n_missed), 0) < {{ var('inactive_after_missed_batches') }}
        and coalesce(max(r.n_batches_without_scope), 0)
            < {{ var('inactive_after_missed_batches') }} as is_active,
    min(m.batch_started_at) filter (where m.n_missed = 1) as first_missed_at,
    min(m.batch_started_at)
        filter (where m.n_missed = {{ var('inactive_after_missed_batches') }}) as inactive_since
from cur
left join missed m using (posting_id)
left join retired r using (posting_id)
group by cur.posting_id
