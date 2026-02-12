"""Abstract base adapter for fathom DB plugins."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Literal, Optional

from engine.selector import Selector
from engine.config import FathomConfig


@dataclass
class CountResult:
    """Result of a count/preflight operation."""

    kind: Literal["exact", "estimate", "unknown"]
    count: Optional[int] = None
    message: Optional[str] = None


@dataclass
class CrawlResult:
    """Result of a crawl operation."""

    bundle_path: Path
    total: int
    succeeded: int
    failed: int
    articles_path: Path
    failed_path: Optional[Path] = None
    provenance_path: Optional[Path] = None


class BaseAdapter(ABC):
    """Interface that every DB adapter must implement.

    Subclasses live in ``dbs/<db_id>/adapter.py`` and are discovered
    via ``registry.yaml``.
    """

    @property
    @abstractmethod
    def db_id(self) -> str:
        """Short identifier, e.g. ``"sillok"``."""
        ...

    @abstractmethod
    def capabilities(self) -> Dict:
        """Declare supported selectors and features.

        Expected return shape::

            {
                "selectors": ["query", "work_scope", "ids"],
                "count_support": {"query": "exact", "work_scope": "estimate"},
            }
        """
        ...

    @abstractmethod
    def count(self, selector: Selector) -> CountResult:
        """Estimate or count articles matching *selector* without crawling."""
        ...

    @abstractmethod
    def crawl(
        self,
        selector: Selector,
        config: FathomConfig,
        limit: Optional[int] = None,
    ) -> CrawlResult:
        """Execute crawl and produce a JSONL v3.1 bundle."""
        ...

    @abstractmethod
    def format_report(self, result: CrawlResult) -> str:
        """Human-readable summary of a completed crawl."""
        ...
