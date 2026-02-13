"""Sillok (조선왕조실록) adapter for fathom."""

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

from sillok_crawler import (
    create_session,
    fetch_article,
    parse_date_info,
    parse_input_file,
    parse_volume_info,
    extract_footnotes,
)
from sillok_search import SillokSearcher, REIGN_ORDER, filter_by_reign_range

from dbs.base import BaseAdapter, CountResult, CrawlResult
from engine.config import FathomConfig
from engine.output import BundleWriter, format_article, format_failed, make_slug
from engine.provenance import ProvenanceBuilder, write_provenance
from engine.selector import Selector


# ─────────────────────────────────────────────────────────────────────
# v3.1 conversion
# ─────────────────────────────────────────────────────────────────────

def _convert_to_v31(raw_content: dict, entry: dict) -> dict:
    """Convert old-format sillok article to JSONL v3.1 schema.

    Args:
        raw_content: Result dict from ``fetch_article()``.
        entry: Input entry dict (id, url, title, date, volume_info).

    Returns:
        Article dict conforming to v3.1 schema.
    """
    # Date info — merge page-extracted into entry
    date_info = dict(entry.get("date", {}))
    if raw_content.get("date_info"):
        page_date = raw_content["date_info"]
        # ganzhi/article_num: page-extracted always wins (more accurate)
        if page_date.get("ganzhi"):
            date_info["ganzhi"] = page_date["ganzhi"]
        if page_date.get("article_num"):
            date_info["article_num"] = page_date["article_num"]
        # reign/year/month/day: fill-only (don't overwrite existing entry values)
        for key in ("reign", "year", "month", "day"):
            page_val = page_date.get(key)
            if not page_val:
                continue
            if not date_info.get(key):
                date_info[key] = page_val

    # Normalise reign: strip sillok name suffix (e.g. "인조실록44권," → "인조")
    reign_raw = date_info.get("reign", "")
    if reign_raw and ("실록" in reign_raw or "보궐정오" in reign_raw):
        _reign_clean = re.sub(r'(실록|보궐정오).*', '', reign_raw).strip()
        if _reign_clean:
            date_info["reign"] = _reign_clean

    # Volume / sillok_name — try entry.volume_info first, fall back to
    # date_info.reign which may contain "인조실록44권," in IDs mode
    vol_info = parse_volume_info(entry.get("volume_info", ""))
    if not vol_info.get("sillok"):
        vol_info = parse_volume_info(reign_raw)

    # Parse page_info string → structured
    page_info_raw = raw_content.get("page_info", "")
    taebaek = ""
    gukpyeon = ""
    if page_info_raw:
        for part in page_info_raw.split(" / "):
            if "태백산사고본" in part:
                taebaek = part.replace("태백산사고본 ", "").strip()
            elif "국편영인본" in part:
                gukpyeon = part.replace("국편영인본 ", "").strip()

    # Category: try to split into major/minor
    categories = []
    for cat_str in raw_content.get("category", []):
        if "-" in cat_str:
            major, minor = cat_str.split("-", 1)
            categories.append({"major": major.strip(), "minor": minor.strip()})
        elif ">" in cat_str:
            major, minor = cat_str.split(">", 1)
            categories.append({"major": major.strip(), "minor": minor.strip()})
        else:
            categories.append({"major": cat_str.strip(), "minor": None})

    # Footnotes: {marker: {term, definition}} → [{footnote_id, term, definition}]
    footnotes = []
    for marker, fn_data in raw_content.get("footnotes", {}).items():
        footnotes.append({
            "footnote_id": str(marker),
            "term": fn_data.get("term", ""),
            "definition": fn_data.get("definition", ""),
        })

    # Text → paragraphs
    translation_text = raw_content.get("translation", "")
    translation_paras = (
        [p for p in translation_text.split("\n\n") if p.strip()]
        if translation_text else []
    )

    original_text = raw_content.get("original", "")
    original_paras = (
        [p for p in original_text.split("\n\n") if p.strip()]
        if original_text else []
    )

    has_translation = bool(
        translation_text
        and translation_text.strip()
        and translation_text != "[크롤링 실패]"
    )

    return {
        "schema_version": "3.1",
        "id": entry.get("id", ""),
        "source": "sillok",
        "metadata": {
            "title": raw_content.get("title") or entry.get("title", ""),
            "sillok_name": vol_info.get("sillok", ""),
            "volume": vol_info.get("volume", 0),
            "date": {
                "reign": date_info.get("reign", ""),
                "year": date_info.get("year", 0),
                "month": date_info.get("month", 0),
                "day": date_info.get("day", 0),
                "ganzhi": date_info.get("ganzhi", ""),
                "article_num": date_info.get("article_num", 1),
                "total_articles": None,
            },
            "western_year": None,
            "chinese_era": None,
            "category": categories,
            "page_info": {"taebaek": taebaek, "gukpyeon": gukpyeon},
            "copyright": None,
        },
        "translation": {
            "paragraphs": translation_paras,
            "persons": [],
        },
        "original": {
            "paragraphs": original_paras,
            "persons": [],
        },
        "footnotes": footnotes,
        "new_translation": None,
        "has_translation": has_translation,
        "has_new_translation": False,
        "url": entry.get("url", ""),
        "image_urls": [],
        "crawled_at": datetime.now(timezone.utc).isoformat(),
        "appendix": {
            "day_articles": None,
            "prev_article_id": None,
            "next_article_id": None,
            "place_annotations": [],
            "book_annotations": [],
        },
    }


# ─────────────────────────────────────────────────────────────────────
# Adapter
# ─────────────────────────────────────────────────────────────────────

class SillokAdapter(BaseAdapter):
    """Adapter for 조선왕조실록 (sillok.history.go.kr)."""

    @property
    def db_id(self) -> str:
        return "sillok"

    def capabilities(self) -> Dict:
        return {
            "selectors": ["query", "work_scope", "ids"],
            "count_support": {"query": "exact"},
        }

    # ── count ────────────────────────────────────────────────────────

    def count(self, selector: Selector) -> CountResult:
        if selector.type == "query":
            return self._count_query(selector)
        if selector.type == "ids":
            n = len(selector.id_list) if selector.id_list else 0
            if selector.source_file:
                entries = parse_input_file(selector.source_file)
                n = len(entries)
            return CountResult(kind="exact", count=n)
        return CountResult(
            kind="unknown",
            message="work_scope 카운트는 지원하지 않습니다. 크롤링을 진행해 주세요.",
        )

    def _count_query(self, selector: Selector) -> CountResult:
        tab = _resolve_tab(selector.layer)
        searcher = SillokSearcher(tab=tab)
        try:
            searcher.setup_session()
            total = searcher.count_only(selector.keywords)
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
            entries = self._resolve_query(selector, limit=limit)
            slug = make_slug(selector.keywords or "query")
            mode = "search"
            raw_req = {
                "keywords": selector.keywords,
                "layer": selector.layer,
                "reign": selector.reign,
            }
            norm_req = {
                "keywords": [k.strip() for k in (selector.keywords or "").split(",")],
                "tab": _resolve_tab(selector.layer),
            }
        elif selector.type == "ids":
            entries = self._resolve_ids(selector)
            slug = make_slug(selector.source_file or "article-ids")
            mode = "ids"
            raw_req = {"id_list": selector.id_list, "source_file": selector.source_file}
            norm_req = {"count": len(entries)}
        elif selector.type == "work_scope":
            entries = self._resolve_work_scope(selector)
            slug = make_slug(selector.work_id or "sillok-scope")
            mode = "work_scope"
            raw_req = {"work_kind": selector.work_kind, "work_id": selector.work_id}
            norm_req = dict(raw_req)
        else:
            raise ValueError(f"지원하지 않는 셀렉터: {selector.type}")

        return self._do_crawl(entries, slug, mode, raw_req, norm_req, config, limit)

    # ── entry resolvers ──────────────────────────────────────────────

    def _resolve_query(self, selector: Selector,
                       limit: Optional[int] = None) -> List[dict]:
        tab = _resolve_tab(selector.layer)
        searcher = SillokSearcher(tab=tab)
        try:
            searcher.setup_session()
            keywords = [k.strip() for k in (selector.keywords or "").split(",") if k.strip()]
            result = searcher.search_multiple_keywords(keywords, limit=limit)
            entries = result["entries"]

            if selector.reign:
                reign_to = selector.options.get("reign_to", selector.reign)
                entries = filter_by_reign_range(entries, selector.reign, reign_to)

            return [_normalise_search_entry(e) for e in entries]
        finally:
            searcher.close()

    def _resolve_ids(self, selector: Selector) -> List[dict]:
        if selector.source_file:
            return parse_input_file(selector.source_file)
        if selector.id_list:
            base_url = "https://sillok.history.go.kr/id"
            return [
                {
                    "id": aid.strip(),
                    "volume_info": "",
                    "date_str": "",
                    "date": {
                        "reign": "", "year": 0, "month": 0,
                        "day": 0, "ganzhi": "", "article_num": 1,
                    },
                    "title": "",
                    "url": f"{base_url}/{aid.strip()}",
                }
                for aid in selector.id_list
            ]
        return []

    def _resolve_work_scope(self, selector: Selector) -> List[dict]:
        """Resolve work_scope selector.

        For sillok, work_scope with work_kind='reign' uses the search API
        with an empty-ish keyword constrained by reign filter. This has
        limitations — the sillok site does not support full reign browsing
        without a keyword. An alternative would be to enumerate volumes.

        If *selector.segment* is provided it is interpreted as a volume
        range ("5" or "5-10").
        """
        # Fallback: cannot browse sillok without keyword.
        # Return empty — the workflow layer should inform the user.
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
        writer = BundleWriter(db_root=db_root, source="sillok", slug=slug)
        bundle_path = writer.open()

        # Provenance setup
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

        task_id = f"sillok-{mode}-001"
        pb.add_task(
            task_id=task_id,
            db="sillok",
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
                url = entry.get("url", "")
                raw = fetch_article(session, url)
                is_failure = raw.get("error") or raw.get("translation") == "[크롤링 실패]"
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
                            article = format_article(article, "sillok")
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

        # Provenance finalize
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
            "📗 실록 크롤링 완료",
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

def _resolve_tab(layer: Optional[str]) -> str:
    """Convert Selector.layer to sillok search tab code."""
    if layer == "translation":
        return "k"
    if layer == "original":
        return "w"
    return layer or "w"


def _normalise_search_entry(raw_entry: dict) -> dict:
    """Normalise a search-result entry for the crawl pipeline."""
    date_info = parse_date_info(raw_entry.get("date", ""))
    return {
        "id": raw_entry["id"],
        "volume_info": raw_entry.get("volume", ""),
        "date_str": raw_entry.get("date", ""),
        "date": date_info,
        "title": raw_entry.get("title", ""),
        "url": raw_entry.get("url", ""),
    }
