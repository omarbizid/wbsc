-- UNCERTAIN MATCHES (never merged; listed for human review). Pairs in different clusters:
--   same_title_different_description : same company, title and city, but one source
--                                      advertises them with different descriptions
--                                      (separate openings, or an edited re-post?)
--   similar_title_same_company       : same company and city; the titles have the same
--                                      level words (senior, lead, II...) and their other
--                                      words overlap by Jaccard >= 0.6
--   same_title_similar_company       : same title and city; company keys differ but one
--                                      contains the other
with k as (
    select
        m.*,
        c.group_key,
        c.cluster_key,
        array(select w from unnest(regexp_split_to_array(m.title_key, ' ')) w
              where w !~ {{ level_words_regex() }} order by w) as core_words,
        array(select w from unnest(regexp_split_to_array(m.title_key, ' ')) w
              where w ~ {{ level_words_regex() }} order by w) as level_words
    from {{ ref('int_posting_match_keys') }} m
    join {{ ref('int_posting_clusters') }} c using (posting_id)
),

pairs as (
    select
        a.posting_id as posting_id_a,
        b.posting_id as posting_id_b,
        a.group_key = b.group_key as same_group,
        a.company_key = b.company_key as same_company,
        a.title_key = b.title_key as same_title,
        a.level_words = b.level_words as same_level,
        cardinality(array(select unnest(a.core_words) intersect select unnest(b.core_words)))::numeric
          / nullif(cardinality(array(select unnest(a.core_words) union select unnest(b.core_words))), 0)
          as title_jaccard
    from k a
    join k b
      on a.posting_id < b.posting_id
     and a.cluster_key <> b.cluster_key
     and a.primary_city is not distinct from b.primary_city
     and (a.company_key = b.company_key
          or (length(a.company_key) >= 4 and length(b.company_key) >= 4
              and (strpos(a.company_key, b.company_key) > 0
                   or strpos(b.company_key, a.company_key) > 0)))
)

select
    posting_id_a,
    posting_id_b,
    case
        when same_group then 'same_title_different_description'
        when same_company then 'similar_title_same_company'
        else 'same_title_similar_company'
    end as match_rule,
    round(title_jaccard, 2) as title_jaccard
from pairs
where same_group
   or (same_company and not same_title and same_level and title_jaccard >= 0.6)
   or (not same_company and same_title)
