"""Configuration system for fathom.

Loading priority: config.json > config.default.json > hardcoded defaults.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


_DEFAULTS = {
    "db_root": "~/DB",
    "enabled_dbs": ["sillok", "sjw", "itkc"],
    "appendix_fields": {"sillok": [], "sjw": [], "itkc": []},
    "language": "ko",
    "extended_provenance": False,
}


@dataclass
class FathomConfig:
    """Runtime configuration for fathom."""

    db_root: str = "~/DB"
    enabled_dbs: List[str] = field(default_factory=lambda: ["sillok", "sjw", "itkc"])
    appendix_fields: Dict[str, List[str]] = field(
        default_factory=lambda: {"sillok": [], "sjw": [], "itkc": []}
    )
    language: str = "ko"
    extended_provenance: bool = False

    def resolved_db_root(self) -> Path:
        """Return db_root as an absolute Path with ~ expanded."""
        return Path(self.db_root).expanduser().resolve()


def get_fathom_root() -> Path:
    """Return the fathom package root directory (repo root).

    Uses ``__file__`` to resolve location regardless of install method
    (symlink or copy).
    """
    return Path(__file__).resolve().parent.parent


def _find_config_file(name: str, base_dir: Optional[Path] = None) -> Optional[Path]:
    """Locate a config file relative to fathom root."""
    root = Path(base_dir) if base_dir else get_fathom_root()
    candidate = root / name
    if candidate.is_file():
        return candidate
    return None


def load_config(base_dir: Optional[Path] = None) -> FathomConfig:
    """Load configuration with priority: config.json > config.default.json > defaults.

    Args:
        base_dir: Override for fathom root (testing).

    Returns:
        Merged FathomConfig.
    """
    merged = dict(_DEFAULTS)

    default_file = _find_config_file("config.default.json", base_dir)
    if default_file:
        merged.update(_read_json(default_file))

    user_file = _find_config_file("config.json", base_dir)
    if user_file:
        merged.update(_read_json(user_file))

    merged = {k: v for k, v in merged.items() if k in _DEFAULTS}

    return FathomConfig(
        db_root=merged.get("db_root", _DEFAULTS["db_root"]),
        enabled_dbs=merged.get("enabled_dbs", _DEFAULTS["enabled_dbs"]),
        appendix_fields=merged.get("appendix_fields", _DEFAULTS["appendix_fields"]),
        language=merged.get("language", _DEFAULTS["language"]),
        extended_provenance=merged.get("extended_provenance", _DEFAULTS["extended_provenance"]),
    )


def save_config(config: FathomConfig, base_dir: Optional[Path] = None) -> Path:
    """Persist config to config.json.

    Args:
        config: FathomConfig to save.
        base_dir: Override for fathom root.

    Returns:
        Path to written config.json.
    """
    root = Path(base_dir) if base_dir else get_fathom_root()
    path = root / "config.json"

    data = {
        "db_root": config.db_root,
        "enabled_dbs": config.enabled_dbs,
        "appendix_fields": config.appendix_fields,
        "language": config.language,
        "extended_provenance": config.extended_provenance,
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")

    return path


def is_first_run(base_dir: Optional[Path] = None) -> bool:
    """True when config.json does not exist yet (first-time user)."""
    return _find_config_file("config.json", base_dir) is None


def _read_json(path: Path) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}
