"""Daily collection → load → dbt build.

```
db_migrate ─┬─ collect_greenhouse ── load_greenhouse ─┐
            ├─ collect_lever ─────── load_lever ──────┼─ dbt_build
            └─ collect_reed ──────── load_reed ───────┘
```

* **collect_<source>** fetches one source into the raw store (`data/raw/…`). It fails only
  when the whole source failed; partial batches succeed and are recorded as partial.
* **load_<source>** loads every raw batch of that source that has no successful load yet.
  It runs even when collection failed (`all_done`), so a failed batch is still recorded
  in `ops` and shows up in source health. Rerunning it never downloads anything.
* **dbt_build** runs after all loads, whatever their outcome, so one failing source never
  stops the others from reaching the dashboard.

The tasks call the `jobintel` CLI in its own virtualenv (see docker/Dockerfile).
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta

from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG

JOBINTEL = os.environ.get("JOBINTEL_BIN", "/opt/jobintel-venv/bin/jobintel")
SOURCES = ("greenhouse", "lever", "reed")

with DAG(
    dag_id="jobintel_daily",
    description="Collect UK data job postings, load them and rebuild the marts",
    schedule="0 6 * * *",              # 06:00 UTC = 07:00 UK summer time
    start_date=datetime(2026, 9, 25),
    catchup=False,                     # a missed day cannot be collected later
    max_active_runs=1,
    default_args={"retries": 1, "retry_delay": timedelta(minutes=20)},
    doc_md=__doc__,
    tags=["jobintel"],
) as dag:
    migrate = BashOperator(task_id="db_migrate", bash_command=f"{JOBINTEL} db migrate")
    dbt_build = BashOperator(
        task_id="dbt_build",
        bash_command=f"{JOBINTEL} transform",
        trigger_rule="all_done",
        execution_timeout=timedelta(minutes=30),
    )
    for source in SOURCES:
        collect = BashOperator(
            task_id=f"collect_{source}",
            bash_command=f"{JOBINTEL} -v collect --source {source} --no-load",
            execution_timeout=timedelta(hours=1),
        )
        load = BashOperator(
            task_id=f"load_{source}",
            bash_command=f"{JOBINTEL} -v load --pending --source {source}",
            trigger_rule="all_done",
            execution_timeout=timedelta(minutes=30),
        )
        migrate >> collect >> load >> dbt_build
