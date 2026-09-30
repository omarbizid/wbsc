# Project plan — Job Market Intelligence Platform

Scope: UK, English-language postings for **data analyst**, **data engineer** and
**analytics engineer** roles, with an emphasis on entry level. Local deployment.

## 1. Source strategy

Three sources. Each one must allow automated access and must not need a login:

| # | Source | Method | Why | Needs |
|---|--------|--------|-----|-------|
| S1 | Greenhouse Job Board API (company career boards) | JSON API | Public, no auth ("Job Board data is publicly available"), full descriptions, stable IDs | curated list of board tokens |
| S2 | Lever-hosted career pages (`jobs.lever.co/<company>`) | **HTML scraping** | robots.txt `Allow: /`, `Crawl-delay: 1`; server-rendered HTML | curated list of company slugs |
| S3 | Reed.co.uk Jobseeker API | JSON API (key) | UK aggregator, supplies the volume of entry-level roles, has a structured salary | **free API key from the client** |

Findings from probing (2026-09-22):
- Company boards carry only 0–11 UK data roles each. They are good for precision and
  cross-source matching, but alone they cannot supply the volume of entry-level roles.
- Reed has the volume. Its robots.txt disallows `/api/` for *crawlers*. The API is a
  keyed developer product with its own terms, which the client must accept when registering.
- Adzuna was a candidate for S3. We rejected it because its API truncates descriptions
  to about 500 characters, which is too short for skill extraction. It stays a fallback.

Every source is documented in `docs/source_register.md` **before** it is implemented.

## 2. Architecture (target)

```
            ┌──────────── Airflow (daily DAG) ─────────────┐
 sources ─► │ collect_<source>  (Python, httpx, retries)   │
            │   └─► raw store: data/raw/<source>/<date>/<batch_id>/ (gz + manifest)
            │ load_<source>     (parse → validate → upsert / quarantine)
            │ dbt build         (staging → intermediate → marts + tests)
            └──────────────────────────────────────────────┘
                              │
                        PostgreSQL ── Streamlit dashboard
```

- **Collection and processing are separate steps.** Collection writes immutable raw
  batches. Processing reads *only* raw batches, so a replay makes no network calls.
- **Batch identity makes processing idempotent.** An observation is unique on
  `(posting_id, batch_id)`. Replaying the same batch upserts the same rows.
- **Versioning.** `posting` (one row per source + source_job_id) and
  `posting_version` (a new row only when the content hash of meaningful fields
  changes) keep the history of meaningful changes.
- **Ops tables:** `collection_batch` (fetch outcome per source per day) and
  `load_run` (status, duration, collected/accepted/rejected/duplicate counts).
  The quarantine table stores rejected records with a reason.
- **Missing vs failed:** a posting is only marked as missing after a *successful*
  batch of its source. Failed batches never deactivate postings.
- **Inactive rule:** a posting becomes inactive when it is absent from 2 consecutive
  successful batches of its source. If it reappears, it is active again.

## 3. Milestones and task breakdown

### M1 — Design and first source
- [x] Probe candidate sources; pick S1–S3
- [x] Repo scaffold, CLAUDE.md, docker-compose (Postgres), `.env.example`
- [x] Source register (S1 active; S2, S3 documented, pending implementation)
- [x] Initial schema (ops / core; raw data kept on disk and indexed by ops.collection_batch) via SQL migrations
- [x] HTTP client: timeouts, bounded retries with backoff, per-host rate limit, UA
- [x] Raw store (gzip + manifest), Greenhouse collector
- [x] Parser → normalised record (title/company clean, location, arrangement, salary, dates)
- [x] Validator + quarantine, idempotent loader
- [x] Tests: parsing, salary, location, idempotent load, DB constraints
- [x] ≥50 postings loaded into Postgres (2026-09-22: 92 in-scope UK postings, 21 companies, from 4,370 raw jobs on 23 boards)
- [ ] **Start daily raw collection immediately** (Windows Task Scheduler / cron) — the
      14 days of real history is on the critical path. Raw batches are replayable,
      so processing can catch up later.

### M2 — Reliable ingestion
- [x] Request caps + incomplete-scope tracking (absence is only meaningful when a scope was fully fetched)
- [x] `jobintel status`: last batch per source, last success, recent load runs with counts
- [x] Lever HTML scraper (BeautifulSoup) + fixtures (2026-09-25: 25 UK postings from 5 companies)
- [x] Reed API collector, tested on synthetic fixtures. **Waiting for the key** to run live and save a real fixture
- [x] Per-source isolation: one failing source never blocks the others
- [x] `replay` command (batch or date range; no network)
- [x] Load-run logging with counts; rerun-without-duplicates test
- [x] Fixture-based acceptance tests: missing salary, missing required field, source down, parser fix + replay

### M3 — Analytical data
- [x] Skill taxonomy (YAML: canonical name, aliases, regex, negative contexts): 38 skills
- [x] Skill extractor (word-boundary aware; Java ≠ JavaScript; "R" handled carefully)
- [x] Role category + seniority classifier (rules, `unknown` fallback, evidence stored)
- [x] dbt project: staging → intermediate (dedup, cross-source matching) → marts
- [x] dbt tests (unique, not_null, accepted_values, relationships, 5 custom, 2 unit tests)
- [x] Duplicate matching: match group → merged; ambiguous/fuzzy → `mart_uncertain_matches` (never merged)
- [x] Labelled evaluation set (20 tune + 50 eval, frozen), report: eval precision 99.4 % / recall 99.4 %. **Needs human re-labelling spot check; re-run with Reed postings**

### M4 — User interface (Streamlit)
- [x] Global filters: role category, seniority, location, arrangement, source, observation date range, active only, merge duplicates
- [x] Views: Overview, Skills (+pairs), Locations, Salaries (per currency/period, n, coverage), Trends (weekly, empty state, "collected sample" label), Job explorer (search, links, evidence), Data quality
- [x] Stale-data banner per source (computed at view time); denominators on every percentage ("n of N")
- [x] Traceability: every aggregate drills down to postings + source URLs
- [x] Aggregation logic in `jobintel.reporting` with unit tests; AppTest smoke test of every view on synthetic data

### M5 — Operational delivery
- [ ] Airflow DAG (per-source collect → load, then dbt build), in docker-compose
- [ ] GitHub Actions: lint (ruff), pytest with a Postgres service, dbt build on fixtures
- [ ] Docs: README (fresh-checkout sample demo), architecture diagram + DB model,
      data dictionary, operational guide, evaluation report
- [ ] Acceptance-test walkthrough script and demo video (3–5 min)

## 4. Acceptance-test mapping

| Test | How it is demonstrated |
|------|------------------------|
| Same batch twice | `jobintel replay --batch X` twice → row counts unchanged (pytest + script) |
| No salary | fixture without salary → posting stored, salary columns NULL |
| "JavaScript" | extractor unit test |
| Unavailable source | fixture/mocked 503 → batch `failed`, other sources `success`, dashboard stale banner |
| Missing required field | fixture → quarantine row with reason, not in marts |
| Fix parser + replay | replay re-parses stored raw; quarantine entry resolved; no HTTP (network blocked in test) |
| Trace a dashboard result | job explorer drill-down with source URLs |
| Fresh checkout | README: `docker compose up` + `make demo` loads labelled sample fixtures |

## 5. Risks and open questions
- **Reed API key**: the client needs to register (free) and accept the terms. Until then, S3 is built against fixtures.
- **Volume**: company boards give low entry-level counts. We will report sample sizes honestly.
- **14-day window**: must start as early as possible. Collection runs on the host scheduler until Airflow is ready.
- Salary conversion across currencies/periods: *not* converted. Salaries are shown separately.
