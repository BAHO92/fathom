"""JSONL v3.1 output utilities for fathom."""

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Dict, Any


def make_slug(text: str) -> str:
    """Create filesystem-safe slug from text.

    - Keep Unicode letters, digits, underscore
    - Replace spaces and special chars with hyphen
    - Remove consecutive hyphens
    - Max 50 chars
    - Return "unnamed" if empty

    Args:
        text: Input text (Korean, Chinese, ASCII, etc.)

    Returns:
        Filesystem-safe slug with hyphens
    """
    if not text:
        return "unnamed"

    slug = re.sub(r'[^\w]+', '-', text)
    slug = slug.strip('-')
    slug = re.sub(r'-+', '-', slug)
    slug = slug.lower()
    slug = slug[:50].rstrip('-')

    return slug if slug else "unnamed"


def make_bundle_path(
    db_root: str,
    source: str,
    slug: str,
    sources: Optional[List[str]] = None
) -> Path:
    """Create bundle folder path.
    
    Format: bndl_{YYYYMMDD-HHMM}--{ID6}__{slug}__src-{srcset}/
    
    Args:
        db_root: Root directory for DB storage
        source: Primary source DB name
        slug: Slug string (should be pre-slugified)
        sources: List of source DBs (defaults to [source])
        
    Returns:
        Path to bundle folder
    """
    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y%m%d-%H%M")
    bundle_id = uuid.uuid4().hex[:6]
    
    # Srcset (canonical order: sillok, sjw, itkc, modern, newslibrary, munzip)
    canonical_order = ['sillok', 'sjw', 'itkc', 'modern', 'newslibrary', 'munzip']
    if sources is None:
        sources = [source]
    
    # Sort sources by canonical order
    srcset_list = sorted(
        set(sources),
        key=lambda x: canonical_order.index(x) if x in canonical_order else 999
    )
    srcset = '-'.join(srcset_list)
    folder_name = f"bndl_{timestamp}--{bundle_id}__{slug}__src-{srcset}"
    
    return Path(db_root) / folder_name


def format_article(raw: dict, source: str, schema_version: str = "3.1") -> dict:
    """Format article to JSONL v3.1 schema.
    
    Adds metadata fields if not present:
    - schema_version
    - source
    - crawled_at
    
    Args:
        raw: Raw article dict from DB adapter
        source: Source DB name
        schema_version: Schema version string
        
    Returns:
        Article dict with v3.1 metadata
    """
    article = raw.copy()
    
    if 'schema_version' not in article:
        article['schema_version'] = schema_version
    
    if 'source' not in article:
        article['source'] = source
    
    if 'crawled_at' not in article:
        article['crawled_at'] = datetime.now(timezone.utc).isoformat()
    
    return article


def format_failed(
    id: str,
    url: str,
    error: str,
    retries: int = 0
) -> dict:
    """Format failed record.
    
    Args:
        id: Article ID that failed
        url: URL that failed
        error: Error message
        retries: Number of retry attempts
        
    Returns:
        Failed record dict
    """
    return {
        "id": id,
        "url": url,
        "error": error,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "retries": retries
    }


def write_jsonl(path: Path, records: List[dict]) -> int:
    """Write records to JSONL file.
    
    Args:
        path: Output file path
        records: List of record dicts
        
    Returns:
        Number of records written
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(path, 'w', encoding='utf-8') as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + '\n')
    
    return len(records)


def append_jsonl(path: Path, record: dict) -> None:
    """Append single record to JSONL file.
    
    Args:
        path: Output file path
        record: Record dict to append
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(record, ensure_ascii=False) + '\n')


class BundleWriter:
    """JSONL v3.1 bundle writer.
    
    Manages bundle folder creation and JSONL file writing.
    
    Usage:
        writer = BundleWriter(
            db_root="/path/to/DB",
            source="sillok",
            slug="song-siyeol"
        )
        writer.open()
        writer.write_article(article_dict)
        writer.write_failed(failed_dict)
        result = writer.close()
    """
    
    def __init__(
        self,
        db_root: str,
        source: str,
        slug: str,
        sources: Optional[List[str]] = None
    ):
        """Initialize bundle writer.
        
        Args:
            db_root: Root directory for DB storage
            source: Primary source DB name
            slug: Slug string (will be slugified if needed)
            sources: List of source DBs (defaults to [source])
        """
        self.db_root = db_root
        self.source = source
        self.slug = make_slug(slug)
        self.sources = sources if sources is not None else [source]
        
        self.bundle_path: Optional[Path] = None
        self.articles_path: Optional[Path] = None
        self.failed_path: Optional[Path] = None
        
        self._articles_file = None
        self._failed_file = None
        
        self._article_count = 0
        self._failed_count = 0
    
    def open(self) -> Path:
        """Open bundle and create folder structure.
        
        Creates:
        - Bundle folder
        - articles.jsonl (empty)
        - failed.jsonl (empty)
        
        Returns:
            Path to bundle folder
        """
        self.bundle_path = make_bundle_path(
            self.db_root,
            self.source,
            self.slug,
            self.sources
        )
        self.bundle_path.mkdir(parents=True, exist_ok=True)
        
        self.articles_path = self.bundle_path / "articles.jsonl"
        self.failed_path = self.bundle_path / "failed.jsonl"
        
        self._articles_file = open(self.articles_path, 'w', encoding='utf-8')
        self._failed_file = open(self.failed_path, 'w', encoding='utf-8')
        
        return self.bundle_path
    
    def write_article(self, article: dict) -> None:
        """Write article to articles.jsonl.
        
        Args:
            article: Article dict (should already have v3.1 schema)
        """
        if self._articles_file is None:
            raise RuntimeError("Bundle not opened. Call open() first.")
        
        self._articles_file.write(json.dumps(article, ensure_ascii=False) + '\n')
        self._article_count += 1
    
    def write_failed(self, failed: dict) -> None:
        """Write failed record to failed.jsonl.
        
        Args:
            failed: Failed record dict
        """
        if self._failed_file is None:
            raise RuntimeError("Bundle not opened. Call open() first.")
        
        self._failed_file.write(json.dumps(failed, ensure_ascii=False) + '\n')
        self._failed_count += 1
    
    def close(self) -> Dict[str, Any]:
        """Close bundle and return result.
        
        Returns:
            CrawlResult dict with:
            - succeeded: Number of successful articles
            - failed: Number of failed records
            - bundle_path: Path to bundle folder
            - articles_path: Path to articles.jsonl
            - failed_path: Path to failed.jsonl
        """
        if self._articles_file:
            self._articles_file.close()
            self._articles_file = None
        
        if self._failed_file:
            self._failed_file.close()
            self._failed_file = None
        
        return {
            'succeeded': self._article_count,
            'failed': self._failed_count,
            'bundle_path': str(self.bundle_path),
            'articles_path': str(self.articles_path),
            'failed_path': str(self.failed_path)
        }


def create_bundle(
    db_root: str,
    source: str,
    slug: str,
    articles: List[dict],
    failed: Optional[List[dict]] = None,
    sources: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Create bundle with articles and failed records (convenience function).
    
    Args:
        db_root: Root directory for DB storage
        source: Primary source DB name
        slug: Slug string
        articles: List of article dicts
        failed: List of failed record dicts (optional)
        sources: List of source DBs (defaults to [source])
        
    Returns:
        CrawlResult dict
    """
    writer = BundleWriter(db_root, source, slug, sources)
    writer.open()
    
    for article in articles:
        writer.write_article(article)
    
    if failed:
        for fail in failed:
            writer.write_failed(fail)
    
    return writer.close()
