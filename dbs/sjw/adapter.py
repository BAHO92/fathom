"""SJW (승정원일기) adapter for fathom."""

from __future__ import annotations

import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Dict, List, Optional

# Add scripts directory to path
_scripts_dir = str(Path(__file__).parent / "scripts")
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from sjw_crawler import (
    create_session,
    fetch_article,
    parse_article_id,
    parse_source_info,
    browse_collect_entries,
    KING_CODES,
    KING_NAMES_TO_CODES,
    SJW_BASE,
)
from sjw_search import SjwSearcher

from dbs.base import BaseAdapter, CountResult, CrawlResult
from engine.config import FathomConfig
from engine.output import BundleWriter, format_article, format_failed, make_slug
from engine.provenance import ProvenanceBuilder, write_provenance
from engine.selector import Selector


# ─────────────────────────────────────────────────────────────────────
# v3.1 conversion
# ─────────────────────────────────────────────────────────────────────

def _convert_to_v31(raw_content: dict, entry: dict) -> dict:
    """Convert old-format SJW article to JSONL v3.1 schema.

    Args:
        raw_content: Result dict from ``fetch_article()``.
        entry: Input entry dict with at minimum ``id``.

    Returns:
        Article dict conforming to v3.1 schema.
    """
    article_id = entry.get("id", "")

    # Date info — prefer source_info, fallback to ID-parsed
    src = raw_content.get("source_info") or {}
    if src.get("reign"):
        date_info = {
            "reign": src["reign"],
            "year": src.get("year", 0),
            "month": src.get("month", 0),
            "day": src.get("day", 0),
            "ganzhi": src.get("ganzhi", ""),
            "article_num": src.get("article_num", 1),
            "total_articles": src.get("total_articles", None),
        }
    else:
        parsed = parse_article_id(article_id)
        date_info = {
            "reign": parsed.get("reign", ""),
            "year": parsed.get("year", 0),
            "month": parsed.get("month", 0),
            "day": parsed.get("day", 0),
            "ganzhi": parsed.get("ganzhi", ""),
            "article_num": parsed.get("article_num", 1),
            "total_articles": None,
        }

    western_year = src.get("western_year") if src.get("western_year") else None
    chinese_era = src.get("chinese_era") if src.get("chinese_era") else None

    # Source info
    source_info = {
        "book_num": src.get("book_num", 0),
        "book_num_talcho": src.get("book_num_talcho", 0),
        "description": src.get("source_info", ""),
    }

    # Text → paragraphs
    original_text = raw_content.get("original", "")
    original_paras = (
        [p for p in original_text.split("\n\n") if p.strip()]
        if original_text else []
    )

    translation_text = raw_content.get("translation", "")
    translation_paras = (
        [p for p in translation_text.split("\n\n") if p.strip()]
        if translation_text else []
    )

    has_translation = raw_content.get("has_translation", False)
    itkc_data_id = raw_content.get("itkc_data_id", "")

    return {
        "schema_version": "3.1",
        "id": article_id,
        "source": "sjw",
        "metadata": {
            "title": raw_content.get("title") or entry.get("title", ""),
            "date": date_info,
            "western_year": western_year,
            "chinese_era": chinese_era,
            "source_info": source_info,
        },
        "original": {
            "paragraphs": original_paras,
        },
        "translation": {
            "paragraphs": translation_paras,
            "title": None,
            "footnotes": [],
            "person_index": [],
            "place_index": [],
        },
        "has_translation": has_translation,
        "itkc_data_id": itkc_data_id,
        "url": f"{SJW_BASE}/id/{article_id}",
        "image_urls": [],
        "crawled_at": datetime.now(timezone.utc).isoformat(),
        "appendix": {
            "person_annotations": [],
            "day_total_articles": None,
        },
    }


# ─────────────────────────────────────────────────────────────────────
# Adapter
# ─────────────────────────────────────────────────────────────────────

class SJWAdapter(BaseAdapter):
    """Adapter for 승정원일기 (sjw.history.go.kr)."""

    @property
    def db_id(self) -> str:
        return "sjw"

    def capabilities(self) -> Dict:
        return {
            "selectors": ["query", "time_range", "work_scope", "ids"],
            "count_support": {"query": "exact"},
        }

    # ── count ────────────────────────────────────────────────────────

    def count(self, selector: Selector) -> CountResult:
        if selector.type == "query":
            return self._count_query(selector)
        if selector.type == "ids":
            n = len(selector.id_list) if selector.id_list else 0
            return CountResult(kind="exact", count=n)
        if selector.type in ("time_range", "work_scope"):
            return CountResult(
                kind="unknown",
                message="time_range/work_scope 카운트는 전체 열람 후에만 파악됩니다.",
            )
        return CountResult(kind="unknown", message=f"지원하지 않는 셀렉터: {selector.type}")

    def _count_query(self, selector: Selector) -> CountResult:
        searcher = SjwSearcher()
        try:
            searcher.setup_session()
            field = selector.options.get("field", "all")
            total, _, _ = searcher.search(
                selector.keywords or "",
                field=field,
            )
            return CountResult(kind="exact", count=total)
        finally:
            searcher.close()

    # ── crawl ────────────────────────────────────────────────────────

    def crawl(
        self,
        selector: Selector,
        config: FathomConfig,
        limit: Optional[int] = None,
    ) -> CrawlResult:
        if selector.type == "query":
            entries = self._resolve_query(selector)
            slug = make_slug(selector.keywords or "sjw-query")
            mode = "search"
            raw_req = {"keywords": selector.keywords, "field": selector.options.get("field", "all")}
            norm_req = {"keywords": [(selector.keywords or "")], "field": selector.options.get("field", "all")}
        elif selector.type == "time_range":
            entries = self._resolve_time_range(selector)
            slug = make_slug(f"{selector.reign or 'sjw'}-{selector.year_from or ''}-{selector.year_to or ''}")
            mode = "time_range"
            raw_req = {"reign": selector.reign, "year_from": selector.year_from, "year_to": selector.year_to}
            norm_req = dict(raw_req)
        elif selector.type == "work_scope":
            entries = self._resolve_work_scope(selector)
            slug = make_slug(selector.work_id or "sjw-scope")
            mode = "work_scope"
            raw_req = {"work_kind": selector.work_kind, "work_id": selector.work_id}
            norm_req = dict(raw_req)
        elif selector.type == "ids":
            entries = self._resolve_ids(selector)
            slug = make_slug("sjw-ids")
            mode = "ids"
            raw_req = {"id_list": selector.id_list}
            norm_req = {"count": len(entries)}
        else:
            raise ValueError(f"지원하지 않는 셀렉터: {selector.type}")

        return self._do_crawl(entries, slug, mode, raw_req, norm_req, config, limit)

    # ── entry resolvers ──────────────────────────────────────────────

    def _resolve_query(self, selector: Selector) -> List[dict]:
        searcher = SjwSearcher()
        try:
            searcher.setup_session()
            field = selector.options.get("field", "all")
            keywords = [k.strip() for k in (selector.keywords or "").split(",") if k.strip()]

            all_entries: List[dict] = []
            seen_ids: set = set()
            for kw in keywords:
                result = searcher.search_and_collect(kw, field=field)
                for e in result["entries"]:
                    if e["id"] not in seen_ids:
                        seen_ids.add(e["id"])
                        all_entries.append(e)
                if kw != keywords[-1]:
                    time.sleep(1)

            return [_normalise_search_entry(e) for e in all_entries]
        finally:
            searcher.close()

    def _resolve_time_range(self, selector: Selector) -> List[dict]:
        reign = selector.reign or ""
        entries = browse_collect_entries(
            reign,
            year_from=selector.year_from,
            year_to=selector.year_to,
        )
        return [_normalise_browse_entry(e) for e in entries]

    def _resolve_work_scope(self, selector: Selector) -> List[dict]:
        """work_scope for SJW = browse entire reign."""
        reign = selector.work_id or ""
        entries = browse_collect_entries(reign)
        return [_normalise_browse_entry(e) for e in entries]

    def _resolve_ids(self, selector: Selector) -> List[dict]:
        if selector.id_list:
            return [
                {
                    "id": aid.strip(),
                    "title": "",
                    "url": f"{SJW_BASE}/id/{aid.strip()}",
                }
                for aid in selector.id_list
            ]
        return []

    # ── core crawl loop ──────────────────────────────────────────────

    def _do_crawl(
        self,
        entries: List[dict],
        slug: str,
        mode: str,
        raw_request: dict,
        normalized_request: dict,
        config: FathomConfig,
        limit: Optional[int],
    ) -> CrawlResult:
        if limit and limit < len(entries):
            entries = entries[:limit]

        db_root = str(config.resolved_db_root())
        writer = BundleWriter(db_root=db_root, source="sjw", slug=slug)
        bundle_path = writer.open()

        # Provenance
        folder_name = bundle_path.name
        bid_match = re.search(r"bndl_(.+?)__", folder_name)
        bundle_id_str = bid_match.group(1) if bid_match else folder_name

        pb = ProvenanceBuilder(
            bundle_id=bundle_id_str,
            folder_name=folder_name,
            extended=config.extended_provenance,
        )
        try:
            from engine import __version__
        except ImportError:
            __version__ = "0.0.0"
        pb.set_tool_info(name="fathom", version=__version__)

        task_id = f"sjw-{mode}-001"
        pb.add_task(
            task_id=task_id,
            db="sjw",
            mode=mode,
            raw_request=raw_request,
            normalized_request=normalized_request,
        )

        total = len(entries)
        succeeded = 0
        failed = 0
        write_lock = Lock()

        def _fetch_one(entry: dict) -> dict:
            session = create_session()
            try:
                article_id = entry.get("id", "")
                raw = fetch_article(session, article_id)
                is_failure = raw.get("error") or raw.get("original") == "[크롤링 실패]"
                if is_failure:
                    return {"ok": False, "entry": entry, "error": raw.get("error", "Unknown")}
                return {"ok": True, "entry": entry, "raw": raw}
            except Exception as exc:
                return {"ok": False, "entry": entry, "error": str(exc)}

        workers = min(4, max(1, total))
        if total > 0:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(_fetch_one, e): e for e in entries}
                for fut in as_completed(futures):
                    res = fut.result()
                    with write_lock:
                        if res["ok"]:
                            article = _convert_to_v31(res["raw"], res["entry"])
                            article = format_article(article, "sjw")
                            writer.write_article(article)
                            succeeded += 1
                        else:
                            rec = format_failed(
                                id=res["entry"].get("id", "unknown"),
                                url=res["entry"].get("url", ""),
                                error=res.get("error", "Unknown"),
                            )
                            writer.write_failed(rec)
                            failed += 1

        bundle_result = writer.close()

        pb.update_task_stats(task_id, selected=total, succeeded=succeeded, failed=failed)
        pb.set_outputs(
            articles_path="articles.jsonl",
            articles_count=succeeded,
            failed_path="failed.jsonl",
            failed_count=failed,
            bundle_root=bundle_path if config.extended_provenance else None,
        )
        prov = pb.build()
        write_provenance(bundle_path / "provenance.json", prov)

        return CrawlResult(
            bundle_path=bundle_path,
            total=total,
            succeeded=succeeded,
            failed=failed,
            articles_path=Path(bundle_result["articles_path"]),
            failed_path=Path(bundle_result["failed_path"]) if failed else None,
            provenance_path=bundle_path / "provenance.json",
        )

    # ── report ───────────────────────────────────────────────────────

    def format_report(self, result: CrawlResult) -> str:
        lines = [
            "📘 승정원일기 크롤링 완료",
            f"   총 대상: {result.total}건",
            f"   성공: {result.succeeded}건",
        ]
        if result.failed:
            lines.append(f"   실패: {result.failed}건")
        lines.append(f"   번들: {result.bundle_path}")
        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────────────────────────────

def _normalise_search_entry(raw_entry: dict) -> dict:
    """Normalise a search-result entry for the crawl pipeline."""
    return {
        "id": raw_entry["id"],
        "title": raw_entry.get("title", ""),
        "url": raw_entry.get("url", f"{SJW_BASE}/id/{raw_entry['id']}"),
    }


def _normalise_browse_entry(raw_entry: dict) -> dict:
    """Normalise a browse-collected entry for the crawl pipeline."""
    return {
        "id": raw_entry.get("id", ""),
        "title": raw_entry.get("title", ""),
        "url": raw_entry.get("url", f"{SJW_BASE}/id/{raw_entry.get('id', '')}"),
    }
