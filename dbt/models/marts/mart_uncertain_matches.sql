-- Possible duplicates that are NOT merged. For advisers / maintainers to review.
select
    m.match_rule,
    m.title_jaccard,
    a.posting_id as posting_id_a,
    a.source_id as source_a,
    a.company_clean as company_a,
    a.title_clean as title_a,
    a.url as url_a,
    b.posting_id as posting_id_b,
    b.source_id as source_b,
    b.company_clean as company_b,
    b.title_clean as title_b,
    b.url as url_b,
    a.primary_city
from {{ ref('int_uncertain_matches') }} m
join {{ ref('dim_postings') }} a on a.posting_id = m.posting_id_a
join {{ ref('dim_postings') }} b on b.posting_id = m.posting_id_b
