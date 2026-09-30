"""Run dbt with connection settings taken from DATABASE_URL (so credentials live only in .env)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

from jobintel.config import PROJECT_ROOT, get_settings

DBT_DIR = PROJECT_ROOT / "dbt"


def dbt_env(database_url: str | None = None) -> dict[str, str]:
    url = urlsplit(database_url or get_settings().database_url or "")
    if not url.hostname:
        raise RuntimeError("DATABASE_URL is not set (see .env.example)")
    env = dict(os.environ)
    env.update({
        "DBT_HOST": url.hostname,
        "DBT_PORT": str(url.port or 5432),
        "DBT_USER": unquote(url.username or ""),
        "DBT_PASSWORD": unquote(url.password or ""),
        "DBT_DBNAME": url.path.lstrip("/"),
        "PYTHONIOENCODING": "utf-8",
    })
    return env


def dbt_executable() -> str:
    candidate = Path(sys.executable).parent / ("dbt.exe" if os.name == "nt" else "dbt")
    return str(candidate) if candidate.exists() else (shutil.which("dbt") or "dbt")


def run_dbt(args: list[str], database_url: str | None = None) -> int:
    cmd = [dbt_executable(), *args, "--project-dir", str(DBT_DIR), "--profiles-dir", str(DBT_DIR)]
    return subprocess.call(cmd, env=dbt_env(database_url), cwd=DBT_DIR)
