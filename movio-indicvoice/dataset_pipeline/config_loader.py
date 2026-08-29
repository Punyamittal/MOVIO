"""Load YAML configs for the dataset pipeline."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from dataset_pipeline.paths import CONFIG_DIR

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore


def _load(name: str) -> dict[str, Any]:
    path = CONFIG_DIR / name
    text = path.read_text(encoding="utf-8")
    if yaml is None:
        # Minimal fallback: only support simple key: value for emergencies
        raise RuntimeError("PyYAML required — pip install pyyaml")
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config {name} must be a mapping")
    return data


def load_dataset_config() -> dict[str, Any]:
    return _load("dataset.yaml")


def load_sources_config() -> dict[str, Any]:
    return _load("sources.yaml")


def load_filtering_config() -> dict[str, Any]:
    return _load("filtering.yaml")


def load_languages_config() -> dict[str, Any]:
    return _load("languages.yaml")


def all_discovery_queries(cfg: dict[str, Any] | None = None) -> list[tuple[str, str]]:
    """Return list of (bucket, query)."""
    cfg = cfg or load_languages_config()
    out: list[tuple[str, str]] = []
    for bucket in (
        "tamil_conversational",
        "indian_english",
        "code_switching",
        "movio_domains",
    ):
        for q in cfg.get(bucket) or []:
            out.append((bucket, str(q)))
    return out
