# One image for Airflow (scheduler + UI) and for the jobintel CLI / Streamlit dashboard.
# jobintel and dbt live in their own virtualenv (/opt/jobintel-venv) so their dependencies
# never conflict with Airflow's. Airflow tasks call /opt/jobintel-venv/bin/jobintel.
FROM apache/airflow:slim-3.3.2-python3.12

# Postgres driver for Airflow's own metadata database (not included in the slim image).
RUN pip install --no-cache-dir "apache-airflow==3.3.2" "psycopg2-binary>=2.9,<3"

USER root
RUN mkdir -p /opt/jobintel /opt/jobintel-venv && chown -R airflow:root /opt/jobintel /opt/jobintel-venv
USER airflow

# Install dependencies first (cached layer), then the project itself in editable mode.
# At runtime docker-compose mounts the repository over /opt/jobintel, so code, config,
# dbt models and data/raw are the ones on the host.
COPY --chown=airflow:root pyproject.toml /opt/jobintel/
COPY --chown=airflow:root src /opt/jobintel/src
RUN /usr/local/bin/python -m venv /opt/jobintel-venv \
 && /opt/jobintel-venv/bin/pip install --no-cache-dir -e "/opt/jobintel[dashboard,dbt]"
COPY --chown=airflow:root . /opt/jobintel

ENV JOBINTEL_BIN=/opt/jobintel-venv/bin/jobintel \
    PYTHONIOENCODING=utf-8
WORKDIR /opt/jobintel
