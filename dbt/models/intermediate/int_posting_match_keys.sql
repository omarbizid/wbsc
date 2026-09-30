-- Normalised keys used to recognise the same job advertised more than once.
select
    posting_id,
    source_id,
    first_seen_at,
    {{ company_key('company_clean') }} as company_key,
    {{ title_key('title_clean') }} as title_key,
    (select min(c) from unnest(location_cities) as c) as primary_city,
    md5(regexp_replace(lower(description_text), '\s+', ' ', 'g')) as description_hash
from {{ ref('int_posting_current') }}
