# CLAUDE.md

Job Market Intelligence Platform: collects UK entry-level data job postings (data analyst,
data engineer, analytics engineer), then extracts skills and classifies roles. Results are
served in a Streamlit dashboard for careers advisers. The plan and milestone checklist are
in `docs/PLAN.md`; keep that checklist updated as work lands.

## Stack
Python 3.12+ (collection/extraction) · PostgreSQL 16 · dbt Core · Airflow · Streamlit ·
Docker Compose · GitHub Actions. Develop on Windows (Git Bash/PowerShell). Everything
must also run in Linux containers.

## Layout
- `src/jobintel/` — Python package
  - `http.py` shared HTTP client (timeouts, bounded retries, per-host rate limit)
  - `raw_store.py` immutable raw batches in `data/raw/<source>/<YYYY-MM-DD>/<batch_id>/`
  - `sources/` one module per source: `fetch()` → raw batch; `parse()` raw → `ParsedPosting`
  - `normalize/` location, salary, working arrangement, text cleaning
  - `validate.py`, `load.py` (idempotent upsert + quarantine), `cli.py`
  - `enrich/` skill extraction (`config/skills.yml`), role/seniority rules, evaluation
  - `reporting/` loads `marts` into pandas (`data.py`) + pure filters/aggregations (`metrics.py`)
- `sql/migrations/` numbered SQL migrations applied by `jobintel db migrate`
- `dbt/` staging → intermediate → marts; business rules (inactive, duplicates) live here · `dashboard/app.py` Streamlit UI (thin; logic belongs in `reporting/metrics.py`) · `airflow/` DAGs (M5)
- `tests/` pytest; `tests/fixtures/<source>/` saved source responses
- `eval/` labelled skill samples: `tune` may be used to adjust rules; `eval` is frozen
  (checksums in `eval/FROZEN.sha256`) and must never be used for tuning
- `docs/` plan, source register, data dictionary, ops guide, evaluation report

## Commands
```bash
docker compose up -d postgres          # local DB (port 5433 on host)
pip install -e ".[dev]"
jobintel db migrate                    # apply sql/migrations
jobintel collect --source greenhouse   # fetch → raw store → load
jobintel replay --batch <id>           # reprocess saved raw, no network
jobintel transform                     # dbt build (models + tests)
jobintel enrich / evaluate eval        # re-derive skills; measure extraction
jobintel dashboard                     # streamlit run dashboard/app.py
pytest                                 # needs DATABASE_URL for DB tests (else skipped)
ruff check .
```

## Non-negotiable rules
- **Never invent data.** Salary, posting date and working arrangement stay NULL/`unknown`
  unless the source states them explicitly. Label any synthetic data as synthetic
  (`is_synthetic`, the `synthetic_` prefix on fixtures).
- **Collection and processing are separate.** Parsers read only raw batches, and replay
  must never make a network request.
- **Idempotency:** observations are unique on `(posting_id, batch_id)`, and versions
  on `(posting_id, content_hash)`. Rerunning a batch must not change row counts.
- **Missing vs failed:** only a *successful* batch can mark a posting as missing.
  Inactive = absent from 2 consecutive successful batches of its source.
- **Uncertain matches go into a separate table.** Never merge them silently.
- Only access sources the way `docs/source_register.md` describes. Respect robots.txt
  and rate limits, and never bypass a login. Document a source before implementing it.
- Credentials come only from the environment or `.env` (gitignored). Never commit secrets.
- One failing source must never stop the other sources.
- Skill matching respects token boundaries ("Java" must not match "JavaScript").

## Conventions
- psycopg 3, plain SQL (no ORM). Timestamps are `timestamptz` in UTC.
- Schemas: `ops` (runs/batches/quarantine), `core` (postings/versions/observations/skills),
  plus dbt schemas `staging`/`marts`.
- Bump `parser_version` (source) / `NORMALIZER_VERSION` / skills.yml `version` /
  `CLASSIFIER_VERSION` whenever that component's output changes, then replay or enrich.
- The dashboard reads only `marts`. Unique jobs = one posting per `cluster_id` among the
  filtered rows (`metrics.unique_jobs`, canonical preferred). Every share shows n and N.
- Add a fixture-based test for every parser fix.
