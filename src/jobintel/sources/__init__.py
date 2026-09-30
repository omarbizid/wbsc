from __future__ import annotations

from jobintel.sources.base import Source
from jobintel.sources.greenhouse import GreenhouseSource
from jobintel.sources.lever import LeverSource
from jobintel.sources.reed import ReedSource

REGISTRY: dict[str, type[Source]] = {
    GreenhouseSource.name: GreenhouseSource,
    LeverSource.name: LeverSource,
    ReedSource.name: ReedSource,
}


def get_source(name: str, sources_config: dict) -> Source:
    try:
        cls = REGISTRY[name]
    except KeyError:
        raise ValueError(f"unknown source {name!r}; known: {sorted(REGISTRY)}") from None
    return cls(sources_config.get(name, {}))
