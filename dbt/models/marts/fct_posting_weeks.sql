-- One row per posting per ISO week (Monday start) in which it was observed.
-- Trends are counts of postings observed in our collected sample, not market totals.
select distinct
    o.posting_id,
    date_trunc('week', o.observed_at)::date as week_start
from {{ ref('stg_observations') }} o
join {{ ref('dim_postings') }} d using (posting_id)
