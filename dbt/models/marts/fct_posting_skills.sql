-- Skills extracted from the current version of each posting (one row per posting x skill).
select
    d.posting_id,
    k.skill,
    k.skill_category,
    k.matched_text,
    k.extractor_version
from {{ ref('dim_postings') }} d
join {{ ref('stg_version_skills') }} k on k.version_id = d.current_version_id
