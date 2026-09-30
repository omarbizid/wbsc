select cluster_id, count(*) filter (where is_canonical) as n_canonical
from {{ ref('dim_postings') }}
group by cluster_id
having count(*) filter (where is_canonical) <> 1
