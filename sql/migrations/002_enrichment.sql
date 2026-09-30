-- 002_enrichment: derived data computed in Python per posting version.
-- Both tables are rebuilt for a version whenever the extractor/classifier version changes
-- (`jobintel enrich`), so they never need a raw replay.

create table core.version_skill (
    version_id         bigint not null references core.posting_version on delete cascade,
    skill              text not null,
    skill_category     text not null,
    matched_text       text not null,     -- the exact text that matched (evidence)
    extractor_version  text not null,
    primary key (version_id, skill)
);
create index on core.version_skill (skill);

create table core.version_classification (
    version_id          bigint primary key references core.posting_version on delete cascade,
    role_category       text not null check (role_category in
        ('data_analyst', 'data_engineer', 'analytics_engineer', 'data_scientist', 'other',
         'unknown')),
    role_evidence       text,
    seniority           text not null check (seniority in
        ('intern', 'entry', 'mid', 'senior', 'lead', 'manager', 'unknown')),
    seniority_source    text not null check (seniority_source in ('title', 'description', 'none')),
    seniority_evidence  text,
    classifier_version  text not null,
    extractor_version   text not null      -- skills in core.version_skill were made by this
);
