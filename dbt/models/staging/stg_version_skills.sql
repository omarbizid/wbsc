select
    version_id,
    skill,
    skill_category,
    matched_text,
    extractor_version
from {{ source('core', 'version_skill') }}
