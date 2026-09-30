-- With include_synthetic = false, no reported posting may come from a synthetic batch.
{% if not var('include_synthetic') %}
select d.posting_id
from {{ ref('dim_postings') }} d
join {{ source('core', 'posting_observation') }} o using (posting_id)
join {{ source('ops', 'collection_batch') }} b using (batch_id)
where b.is_synthetic
  and o.version_id = d.current_version_id
{% else %}
select 1 where false
{% endif %}
