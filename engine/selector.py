"""Selector schema and parsing for fathom crawl requests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Literal, Optional


SELECTOR_TYPES = ("query", "time_range", "work_scope", "ids")


@dataclass
class Selector:
    """Unified selector for all DB crawl operations.

    Four selector types:
      - query: keyword full-text search
      - time_range: calendar/era-based date range
      - work_scope: full or partial work/series/reign collection
      - ids: user-provided ID list or file
    """

    type: Literal["query", "time_range", "work_scope", "ids"]

    # --- query fields ---
    keywords: Optional[str] = None
    layer: Optional[str] = None  # "original" | "translation" | None (both)

    # --- time_range fields ---
    reign: Optional[str] = None
    year_from: Optional[int] = None
    year_to: Optional[int] = None

    # --- work_scope fields ---
    work_kind: Optional[str] = None  # "reign" | "collection" | "series"
    work_id: Optional[str] = None
    segment: Optional[str] = None

    # --- ids fields ---
    id_list: Optional[List[str]] = None
    source_file: Optional[str] = None

    # --- common options ---
    options: dict = field(default_factory=dict)


def parse_selector(raw: dict) -> Selector:
    """Parse raw dict into a validated Selector.

    Args:
        raw: Dict with at minimum ``{"type": "<selector_type>", ...}``

    Returns:
        Validated Selector instance.

    Raises:
        ValueError: If required fields are missing or type is invalid.
    """
    if not isinstance(raw, dict):
        raise ValueError(f"Expected dict, got {type(raw).__name__}")

    sel_type = raw.get("type")
    if sel_type not in SELECTOR_TYPES:
        raise ValueError(
            f"Invalid selector type '{sel_type}'. "
            f"Must be one of: {', '.join(SELECTOR_TYPES)}"
        )

    selector = Selector(
        type=sel_type,
        keywords=raw.get("keywords"),
        layer=raw.get("layer"),
        reign=raw.get("reign"),
        year_from=raw.get("year_from"),
        year_to=raw.get("year_to"),
        work_kind=raw.get("work_kind"),
        work_id=raw.get("work_id"),
        segment=raw.get("segment"),
        id_list=raw.get("id_list"),
        source_file=raw.get("source_file"),
        options=raw.get("options", {}),
    )

    errors = _validate_required(selector)
    if errors:
        raise ValueError("; ".join(errors))

    return selector


def validate_selector(selector: Selector, capabilities: dict) -> List[str]:
    """Check selector against DB capabilities.

    Args:
        selector: Parsed Selector instance.
        capabilities: Dict from ``BaseAdapter.capabilities()``.
            Expected key: ``"selectors": ["query", ...]``.

    Returns:
        List of error messages (empty if valid).
    """
    errors: List[str] = []

    supported = capabilities.get("selectors", [])
    if selector.type not in supported:
        errors.append(
            f"Selector type '{selector.type}' is not supported by this DB. "
            f"Supported: {', '.join(supported)}"
        )

    errors.extend(_validate_required(selector))
    return errors


def _validate_required(selector: Selector) -> List[str]:
    """Return list of validation error strings."""
    errors: List[str] = []

    if selector.type == "query":
        if not selector.keywords:
            errors.append("'keywords' is required for query selector")

    elif selector.type == "time_range":
        if not selector.reign:
            errors.append("'reign' is required for time_range selector")

    elif selector.type == "work_scope":
        if not selector.work_kind:
            errors.append("'work_kind' is required for work_scope selector")
        if not selector.work_id:
            errors.append("'work_id' is required for work_scope selector")

    elif selector.type == "ids":
        if not selector.id_list and not selector.source_file:
            errors.append(
                "'id_list' or 'source_file' is required for ids selector"
            )

    return errors
