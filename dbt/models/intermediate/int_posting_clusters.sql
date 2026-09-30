-- LIKELY DUPLICATES (merged for counting). A "match group" is postings with the same
-- normalised company, normalised title and primary city (or both without a city).
--   * Across sources: postings in a match group are merged (the same advert syndicated).
--   * Within one source: postings are merged only if their descriptions are identical
--     (a re-post under a new ID). Two different descriptions with the same title are
--     treated as separate openings; if that happens, the whole group is NOT merged
--     across sources either (we cannot tell which opening matches which) and the pairs
--     are listed in int_uncertain_matches instead.
-- One posting per cluster is canonical: company career sources first (the original
-- advert), then the earliest first seen, then the lowest id.
with keyed as (
    select
        *,
        company_key || '|' || title_key || '|' || coalesce(primary_city, '-') as group_key,
        case when source_id in ('greenhouse', 'lever') then 1 else 2 end as source_rank
    from {{ ref('int_posting_match_keys') }}
),

per_source as (
    select group_key, source_id, count(distinct description_hash) as n_descriptions
    from keyed
    group by group_key, source_id
),

groups as (
    select group_key, max(n_descriptions) > 1 as is_ambiguous
    from per_source
    group by group_key
),

clustered as (
    select
        k.*,
        g.is_ambiguous,
        case when g.is_ambiguous
             then k.group_key || '|' || k.source_id || '|' || k.description_hash
             else k.group_key end as cluster_key
    from keyed k
    join groups g using (group_key)
),

cluster_sources as (
    select cluster_key, count(distinct source_id) as cluster_n_sources
    from clustered
    group by cluster_key
)

select
    c.posting_id,
    c.group_key,
    c.cluster_key,
    c.is_ambiguous as match_group_ambiguous,
    min(c.posting_id) over (partition by c.cluster_key) as cluster_id,
    count(*) over (partition by c.cluster_key) as cluster_size,
    cs.cluster_n_sources,
    row_number() over (
        partition by c.cluster_key order by c.source_rank, c.first_seen_at, c.posting_id
    ) = 1 as is_canonical
from clustered c
join cluster_sources cs using (cluster_key)
