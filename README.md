# Job Market Intelligence Platform

This platform collects UK job postings for **data analyst, data engineer and analytics
engineer** roles, with an emphasis on entry level. The data comes only from sources that
permit automated access. The pipeline normalises each posting, tracks its history, and
extracts skills, and serves a dashboard for careers advisers.

> Status: **Milestone 4** (Streamlit dashboard on top of the dbt marts). Reed runs once `REED_API_KEY` is set. See [docs/PLAN.md](docs/PLAN.md) for
> the full plan and milestone checklist.

## Quick start

Prerequisites: Docker Desktop, Python ≥ 3.11.

```bash
cp .env.example .env              # then set POSTGRES_PASSWORD (and the same value in DATABASE_URL)
docker compose up -d postgres     # PostgreSQL 16 on localhost:5433

python -m venv .venv
.venv/Scripts/activate            # Windows;  source .venv/bin/activate on Linux/macOS
pip install -e ".[dev]"

jobintel db migrate               # create schemas ops/core
jobintel collect --all            # fetch → data/raw/… → load into PostgreSQL
jobintel replay --all             # reprocess saved raw data, no network access
jobintel status                   # collection log: last batch per source, recent load runs
jobintel transform                # dbt build: marts + data tests (schemas staging/intermediate/marts)
jobintel enrich                   # recompute skills/roles after changing config/skills.yml or rules
jobintel evaluate eval            # skill extraction precision/recall on the labelled sample
jobintel dashboard                # Streamlit dashboard on http://localhost:8501 (reads marts)
pytest                            # unit + database tests (DB tests skip without DATABASE_URL)
```

Each `collect` prints one line per source, showing the batch status and the load counts
(collected / accepted / rejected / duplicate / out of scope).

## How it works

```
source ──fetch──► data/raw/<source>/<date>/<batch_id>/   (immutable, gzip + manifest.json)
                           │
                        parse (no network) → validate → normalise
                           │                     │
                           │                     └─► ops.quarantine (invalid, with reason)
                           ▼
          core.posting ─< core.posting_version ─< core.posting_observation
          (identity)       (content history)        (sighting per batch)
```

- **Collection and processing are separate.** Processing reads only saved raw batches, so
  `replay` can rebuild everything after a parser fix without touching the source.
- **Idempotent loads.** An observation is unique per `(posting, batch)`, and a version per
  `(posting, content_hash)`. Loading the same batch twice changes nothing.
- **Failures are isolated.** Each source (and each board within a source) succeeds or fails
  on its own, and its status is recorded in `ops.collection_batch` / `ops.batch_scope`.
- **Missing values stay missing.** Salary, posting date and working arrangement are only
  filled from explicit statements.

## Database model (current)

| Table | Grain | Purpose |
|-------|-------|---------|
| `ops.source` | source | registry of sources (see [source register](docs/source_register.md)) |
| `ops.collection_batch` | fetch of one source | status `success`/`partial`/`failed`, timings, raw path |
| `ops.batch_scope` | board/company/query in a batch | whether that scope was fetched OK. Absence is only meaningful after a successful scope |
| `ops.load_run` | processing pass over a batch | live/replay, parser version, duration, collected/accepted/rejected/duplicate counts |
| `ops.quarantine` | invalid record per batch | reason code + details. Resolved automatically when a replay loads it |
| `core.posting` | (source, source_job_id) | business identity, first/last seen |
| `core.posting_version` | meaningful content change | original + cleaned title/company, location fields, arrangement, salary, dates, description |
| `core.posting_observation` | (posting, batch) | when each posting was seen, and which version was seen |

## Dashboard

`jobintel dashboard` (or `streamlit run dashboard/app.py`) opens the adviser dashboard. It
reads only the dbt `marts` schema, so run `jobintel transform` after collecting to refresh
it. Data is cached for 5 minutes.

| View | Shows |
|------|-------|
| Overview | Postings, share still advertised / entry level / with salary / with arrangement; role, seniority, arrangement and source breakdowns |
| Skills | Share of postings mentioning each skill, skill pairs, postings with the matched text as evidence |
| Locations | Postings per city, arrangement by city |
| Salaries | Coverage per source; min / quartiles / median / max per currency and pay period (never converted; statistics withheld below 5 salaries) |
| Trends | Postings observed per week, newly seen per week (empty state until 2 weeks exist) |
| Job explorer | Search, links to the original adverts, and every derived field with its evidence and duplicate copies |
| Data quality | Source freshness and failures, uncertain duplicate pairs, recent load runs |

Filters in the sidebar (role, seniority, city, arrangement, source, observation dates,
active only, merge duplicates) apply to every view. Every percentage is shown as
"n of N". Every chart has a "Show the postings behind these figures" drill-down that
links to the source adverts. A warning banner appears when a source has had no successful
collection for 36 hours. The logic lives in `src/jobintel/reporting/`, where it is
unit-tested (`tests/test_reporting.py`) apart from the UI.

## Daily collection

Until Airflow is added (Milestone 5), [scripts/collect_daily.ps1](scripts/collect_daily.ps1)
runs the collection once a day through Windows Task Scheduler. The registration command
is in the script header. Logs are written to `logs/`.

## Documentation

- [Project plan and milestones](docs/PLAN.md)
- [Source register](docs/source_register.md): access rules, methods, rate limits
- [Data dictionary](docs/data_dictionary.md): fields, derived rules (arrangement, salary, inactive, duplicates)
- [Evaluation report](docs/evaluation_report.md): skill extraction precision/recall and known limitations
- Operational guide: Milestone 5
