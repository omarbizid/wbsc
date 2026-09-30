-- An inactive posting must have missed at least the configured number of successful
-- collections; failures alone can never deactivate it.
select posting_id
from {{ ref('dim_postings') }}
where not is_active
  and n_successful_batches_missed < {{ var('inactive_after_missed_batches') }}
