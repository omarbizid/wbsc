-- One row per posting that has at least one reportable observation, with the content
-- of its most recently observed version.
with latest as (
    select distinct on (posting_id) posting_id, version_id
    from {{ ref('stg_observations') }}
    order by posting_id, observed_at desc
)

select
    s.posting_id,
    s.source_id,
    p.source_job_id,
    s.scope_key,
    s.first_seen_at,
    s.last_seen_at,
    s.last_seen_batch_started_at,
    s.n_observations,
    s.n_versions,
    v.version_id,
    v.url,
    v.title_raw,
    v.title_clean,
    v.company_raw,
    v.company_clean,
    v.location_raw,
    v.location_cities,
    v.location_country,
    v.working_arrangement,
    v.arrangement_evidence,
    v.description_text,
    v.salary_min,
    v.salary_max,
    v.salary_currency,
    v.salary_period,
    v.salary_period_inferred,
    v.salary_source,
    v.salary_raw,
    v.posted_date,
    v.parser_version,
    v.role_category,
    v.role_evidence,
    v.seniority,
    v.seniority_source,
    v.seniority_evidence
from {{ ref('int_posting_last_seen') }} s
join latest l using (posting_id)
join {{ ref('stg_postings') }} p using (posting_id)
join {{ ref('stg_posting_versions') }} v on v.version_id = l.version_id
