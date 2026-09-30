-- 001_init: operational metadata (ops) and normalised postings (core).
-- The migration runner records applied files in ops.schema_migrations.

create schema if not exists ops;
create schema if not exists core;

-- ---------------------------------------------------------------- ops
create table ops.source (
    source_id     text primary key,
    display_name  text not null,
    method        text not null check (method in ('json_api', 'html_scrape')),
    base_url      text not null
);

insert into ops.source (source_id, display_name, method, base_url) values
    ('greenhouse', 'Greenhouse job boards (company career pages)', 'json_api',
     'https://boards-api.greenhouse.io/v1/boards/'),
    ('lever', 'Lever-hosted career pages', 'html_scrape', 'https://jobs.lever.co/'),
    ('reed', 'Reed.co.uk Jobseeker API', 'json_api', 'https://www.reed.co.uk/api/1.0/');

-- One fetch of one source. Written by the collector; immutable raw files live on disk.
create table ops.collection_batch (
    batch_id        uuid primary key,
    source_id       text not null references ops.source,
    started_at      timestamptz not null,
    finished_at     timestamptz,
    status          text not null check (status in ('running', 'success', 'partial', 'failed')),
    n_items         integer not null default 0 check (n_items >= 0),
    n_failed_items  integer not null default 0 check (n_failed_items >= 0),
    error           text,
    raw_path        text not null,
    is_synthetic    boolean not null default false,
    check (finished_at is null or finished_at >= started_at)
);
create index on ops.collection_batch (source_id, started_at);

-- Outcome per scope (board / company slug / search query) inside a batch.
-- Absence of a posting is only meaningful when its scope was fetched successfully.
create table ops.batch_scope (
    batch_id   uuid not null references ops.collection_batch on delete cascade,
    scope_key  text not null,
    status     text not null check (status in ('success', 'failed')),
    n_records  integer,
    error      text,
    primary key (batch_id, scope_key)
);

-- One processing pass over one batch (live load or replay).
create table ops.load_run (
    load_run_id     bigserial primary key,
    batch_id        uuid not null references ops.collection_batch,
    mode            text not null check (mode in ('live', 'replay')),
    parser_version  text not null,
    started_at      timestamptz not null default now(),
    finished_at     timestamptz,
    status          text not null check (status in ('running', 'success', 'failed')),
    n_collected     integer not null default 0,  -- records parsed out of the raw batch
    n_out_of_scope  integer not null default 0,  -- not UK / not a data-family title / not English
    n_accepted      integer not null default 0,  -- valid in-scope records loaded
    n_rejected      integer not null default 0,  -- quarantined
    n_duplicate     integer not null default 0,  -- repeated within batch or already observed (rerun)
    n_new_postings  integer not null default 0,
    n_new_versions  integer not null default 0,
    error           text
);
create index on ops.load_run (batch_id);

-- Invalid records, keyed per batch so that replays update rather than duplicate.
create table ops.quarantine (
    quarantine_id   bigserial primary key,
    batch_id        uuid not null references ops.collection_batch,
    source_id       text not null references ops.source,
    record_key      text not null,       -- source_job_id if known, else raw file + index
    reason          text not null,       -- machine-readable code, e.g. missing_required_field
    details         jsonb not null default '{}'::jsonb,
    raw_ref         text,
    parser_version  text not null,
    load_run_id     bigint references ops.load_run,
    first_seen_at   timestamptz not null default now(),
    last_seen_at    timestamptz not null default now(),
    resolved_at     timestamptz,         -- set when a later replay loads the record successfully
    unique (batch_id, record_key)
);

-- ---------------------------------------------------------------- core
-- Business identity of a posting: one row per (source, source_job_id).
create table core.posting (
    posting_id     bigserial primary key,
    source_id      text not null references ops.source,
    source_job_id  text not null check (source_job_id <> ''),
    scope_key      text not null,
    first_seen_at  timestamptz not null,
    last_seen_at   timestamptz not null,
    unique (source_id, source_job_id),
    check (last_seen_at >= first_seen_at)
);

-- Content versions: a new row only when meaningful content changes (content_hash).
create table core.posting_version (
    version_id            bigserial primary key,
    posting_id            bigint not null references core.posting on delete cascade,
    content_hash          text not null,
    parser_version        text not null,
    url                   text not null check (url ~ '^https?://'),
    title_raw             text not null check (title_raw <> ''),
    title_clean           text not null,
    company_raw           text not null check (company_raw <> ''),
    company_clean         text not null,
    location_raw          text,
    location_cities       text[] not null default '{}',
    location_country      text,             -- ISO 3166-1 alpha-2 when determinable
    is_uk                 boolean not null,
    working_arrangement   text not null default 'unknown'
        check (working_arrangement in ('remote', 'hybrid', 'on-site', 'unknown')),
    arrangement_evidence  text,
    description_text      text not null,
    salary_min            numeric(12, 2) check (salary_min > 0),
    salary_max            numeric(12, 2) check (salary_max > 0),
    salary_currency       text check (salary_currency ~ '^[A-Z]{3}$'),
    salary_period         text check (salary_period in ('year', 'month', 'week', 'day', 'hour')),
    salary_period_inferred boolean,
    salary_source         text check (salary_source in ('structured', 'text')),
    salary_raw            text,
    posted_date           date,
    source_updated_at     timestamptz,
    language              text,
    quality_flags         text[] not null default '{}',
    first_seen_at         timestamptz not null,
    created_at            timestamptz not null default now(),
    unique (posting_id, content_hash),
    check (salary_min is null or salary_max is null or salary_min <= salary_max),
    check ((salary_min is null and salary_max is null) or salary_currency is not null)
);
create index on core.posting_version (posting_id);

-- One sighting of a posting in one batch. The primary key makes reruns idempotent.
create table core.posting_observation (
    posting_id   bigint not null references core.posting on delete cascade,
    batch_id     uuid not null references ops.collection_batch,
    version_id   bigint not null references core.posting_version,
    observed_at  timestamptz not null,
    load_run_id  bigint not null references ops.load_run,
    primary key (posting_id, batch_id)
);
create index on core.posting_observation (batch_id);
