select
    l.load_run_id,
    l.batch_id,
    b.source_id,
    l.mode,
    l.parser_version,
    l.started_at,
    l.finished_at,
    extract(epoch from l.finished_at - l.started_at) as duration_seconds,
    l.status,
    l.n_collected,
    l.n_accepted,
    l.n_rejected,
    l.n_duplicate,
    l.n_out_of_scope,
    l.n_new_postings,
    l.n_new_versions,
    l.error
from {{ source('ops', 'load_run') }} l
join {{ source('ops', 'collection_batch') }} b using (batch_id)
