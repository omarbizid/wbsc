"""Runtime settings from the environment (optionally a local .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]

load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    database_url: str | None
    raw_data_dir: Path
    user_agent: str
    reed_api_key: str | None
    sources_config: Path


def get_settings() -> Settings:
    raw_dir = Path(os.environ.get("RAW_DATA_DIR", PROJECT_ROOT / "data" / "raw"))
    if not raw_dir.is_absolute():
        raw_dir = PROJECT_ROOT / raw_dir
    return Settings(
        database_url=os.environ.get("DATABASE_URL") or None,
        raw_data_dir=raw_dir,
        user_agent=os.environ.get(
            "USER_AGENT", "jobintel-research/0.1 (careers advisory research)"
        ),
        reed_api_key=os.environ.get("REED_API_KEY") or None,
        sources_config=Path(
            os.environ.get("SOURCES_CONFIG", PROJECT_ROOT / "config" / "sources.yml")
        ),
    )


def load_sources_config(path: Path | None = None) -> dict:
    path = path or get_settings().sources_config
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}
