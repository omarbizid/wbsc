#!/usr/bin/env bash
# Start Airflow in one container (scheduler, DAG processor, triggerer and web UI).
# `airflow standalone` is Airflow's single-machine mode, which suits this local deployment.
set -euo pipefail

# Airflow keeps its own tables in a separate database ("airflow") on the same server.
/opt/jobintel-venv/bin/python - <<'EOF'
import os, psycopg
with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
    if not conn.execute("select 1 from pg_database where datname = 'airflow'").fetchone():
        conn.execute("create database airflow")
        print("created database airflow")
EOF

exec airflow standalone
