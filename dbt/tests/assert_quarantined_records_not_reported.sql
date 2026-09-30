-- A record that is quarantined (unresolved) in a batch must not have produced an
-- observation in that same batch: invalid data never silently enters reporting.
select q.batch_id, q.record_key
from {{ ref('stg_quarantine') }} q
join {{ source('core', 'posting') }} p
  on p.source_id = q.source_id and p.source_job_id = q.record_key
join {{ source('core', 'posting_observation') }} o
  on o.posting_id = p.posting_id and o.batch_id = q.batch_id
where q.is_open
