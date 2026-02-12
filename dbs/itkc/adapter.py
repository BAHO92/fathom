"""ITKC / Munzip (한국고전종합DB 문집) adapter for fathom."""

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

from munzip_crawler import (
    fetch_api,
    fetch_article_list_search,
    fetch_article_list_full,
    fetch_article_content,
    parse_author,
    parse_seo_myeong,
    get_sec_id_for_collection,
    clean_text,
    WEB_BASE,
)

from dbs.base import BaseAdapter, CountResult, CrawlResult
from engine.config import FathomConfig
from engine.output import BundleWriter, format_article, format_failed, make_slug
from engine.provenance import ProvenanceBuilder, write_provenance
from engine.selector import Selector


# ─────────────────────────────────────────────────────────────────────
# v3.1 conversion
# ─────────────────────────────────────────────────────────────────────

def _convert_to_v31(content: dict, api_article: dict) -> dict:
    """Convert old-format ITKC/munzip article to JSONL v3.1 schema.

    Args:
        content: Result dict from ``fetch_article_content()``.
        api_article: Metadata dict from OpenAPI listing (자료ID, 기사명, …).

    Returns:
        Article dict conforming to v3.1 munzip schema.
    """
    data_id = api_article.get("자료ID", "")

    # Author
    author_raw = parse_author(api_article.get("저자", ""))
    birth_year = api_article.get("저자생년")
    death_year = api_article.get("저자몰년")
    author_raw["birth_year"] = int(birth_year) if birth_year else None
    author_raw["death_year"] = int(death_year) if death_year else None

    # Seo myeong (서명)
    seo_parsed = parse_seo_myeong(api_article.get("서명", ""))

    # Item ID from data_id: ITKC_MO_0367A_... → ITKC_MO
    parts = data_id.split("_")
    item_id = f"{parts[0]}_{parts[1]}" if len(parts) >= 2 else ""
    seo_ji_id = "_".join(parts[:3]) if len(parts) >= 3 else ""

    # Original text → sections[].lines[]
    original_text = content.get("original", "")
    original_lines = [ln for ln in original_text.split("\n\n") if ln.strip()] if original_text else []
    original_sections = []
    if original_lines:
        original_sections.append({
            "index": 0,
            "lines": original_lines,
            "annotations": [],
        })

    # Translation text → paragraphs[{index, text, footnote_markers}]
    translation_text = content.get("translation", "")
    translation_texts = [p for p in translation_text.split("\n\n") if p.strip()] if translation_text else []
    translation_paragraphs = [
        {"index": i, "text": txt, "footnote_markers": []}
        for i, txt in enumerate(translation_texts)
    ]

    has_translation = content.get("has_translation", False)

    # URL construction
    url = f"{WEB_BASE}/dir/item?itemId={parts[1] if len(parts) >= 2 else 'MO'}#/dir/node?dataId={data_id}"

    return {
        "schema_version": "3.1",
        "id": data_id,
        "source": "munzip",
        "metadata": {
            "dci": api_article.get("DCI_s", None),
            "title": content.get("title") or api_article.get("기사명", ""),
            "title_ko": content.get("title_ko", None),
            "seo_myeong": seo_parsed.get("name", ""),
            "seo_myeong_hanja": seo_parsed.get("name_hanja", ""),
            "gwon_cha": api_article.get("권차명", None),
            "mun_che": api_article.get("문체명", None),
            "mun_che_category": api_article.get("문체분류", None),
            "author": author_raw,
            "jibsu": api_article.get("집수번호", None),
            "item_id": item_id,
            "seo_ji_id": seo_ji_id,
            "ja_ryo_gubun": api_article.get("자료구분", None),
            "ganhaeng_gigan": api_article.get("간행기간", None),
            "ganhaeng_year": api_article.get("간행년", None),
            "ganhaeng_cheo": api_article.get("간행처", None),
            "translator": api_article.get("역자", None),
        },
        "original": {
            "title": content.get("title", ""),
            "title_annotations": [],
            "sections": original_sections,
        },
        "translation": {
            "title": content.get("title_ko", ""),
            "paragraphs": translation_paragraphs,
            "footnotes": [],
        },
        "has_translation": has_translation,
        "url": url,
        "crawled_at": datetime.now(timezone.utc).isoformat(),
        "appendix": {
            "page_markers": [],
            "indent_levels": None,
        },
    }


# ─────────────────────────────────────────────────────────────────────
# Adapter
# ─────────────────────────────────────────────────────────────────────

class ITKCAdapter(BaseAdapter):
    """Adapter for 한국고전종합DB / 문집 (db.itkc.or.kr)."""

    @property
    def db_id(self) -> str:
        return "itkc"

    def capabilities(self) -> Dict:
        return {
            "selectors": ["query", "work_scope", "ids"],
            "count_support": {"query": "exact", "work_scope": "exact"},
        }

    # ── count ────────────────────────────────────────────────────────

    def count(self, selector: Selector) -> CountResult:
        if selector.type == "query":
            return self._count_query(selector)
        if selector.type == "work_scope":
            return self._count_work_scope(selector)
        if selector.type == "ids":
            n = len(selector.id_list) if selector.id_list else 0
            return CountResult(kind="exact", count=n)
        return CountResult(kind="unknown", message=f"지원하지 않는 셀렉터: {selector.type}")

    def _count_query(self, selector: Selector) -> CountResult:
        collection_id = selector.work_id or selector.options.get("collection")
        keywords = selector.keywords or ""
        sec_id = selector.options.get("secId", "MO_BD")
        if collection_id and sec_id == "MO_BD":
            sec_id = get_sec_id_for_collection(collection_id, "BD")

        if collection_id:
            q_param = f"query†{keywords}$opDir†{collection_id}"
        else:
            q_param = f"query†{keywords}"

        result = fetch_api({"secId": sec_id, "q": q_param, "start": 0, "rows": 1})
        return CountResult(kind="exact", count=result["total_count"])

    def _count_work_scope(self, selector: Selector) -> CountResult:
        collection_id = selector.work_id or ""
        sec_id = get_sec_id_for_collection(collection_id, "GS")
        q_param = f"opDir†{collection_id}"
        result = fetch_api({"secId": sec_id, "q": q_param, "start": 0, "rows": 1})
        return CountResult(kind="exact", count=result["total_count"])

    # ── crawl ────────────────────────────────────────────────────────

    def crawl(
        self,
        selector: Selector,
        config: FathomConfig,
        limit: Optional[int] = None,
    ) -> CrawlResult:
        if selector.type == "query":
            api_articles = self._resolve_query(selector, limit)
            slug = make_slug(selector.keywords or "itkc-query")
            mode = "search"
            raw_req = {
                "keywords": selector.keywords,
                "collection": selector.work_id or selector.options.get("collection"),
            }
            norm_req = dict(raw_req)
        elif selector.type == "work_scope":
            api_articles = self._resolve_work_scope(selector, limit)
            slug = make_slug(selector.work_id or "itkc-collection")
            mode = "collection"
            raw_req = {"work_kind": selector.work_kind, "work_id": selector.work_id}
            norm_req = dict(raw_req)
        elif selector.type == "ids":
            api_articles = self._resolve_ids(selector)
            slug = make_slug("itkc-ids")
            mode = "ids"
            raw_req = {"id_list": selector.id_list}
            norm_req = {"count": len(api_articles)}
        else:
            raise ValueError(f"지원하지 않는 셀렉터: {selector.type}")

        return self._do_crawl(api_articles, slug, mode, raw_req, norm_req, config, limit)

    # ── resolvers ────────────────────────────────────────────────────

    def _resolve_query(self, selector: Selector, limit: Optional[int]) -> List[dict]:
        collection_id = selector.work_id or selector.options.get("collection")
        keywords = selector.keywords or ""
        sec_id = selector.options.get("secId", "MO_BD")
        if collection_id and sec_id == "MO_BD":
            sec_id = get_sec_id_for_collection(collection_id, "BD")

        return fetch_article_list_search(
            collection_id=collection_id,
            query=keywords,
            sec_id=sec_id,
            limit=limit,
        )

    def _resolve_work_scope(self, selector: Selector, limit: Optional[int]) -> List[dict]:
        collection_id = selector.work_id or ""
        return fetch_article_list_full(collection_id, limit=limit)

    def _resolve_ids(self, selector: Selector) -> List[dict]:
        """For IDs mode, create minimal api_article dicts."""
        if selector.id_list:
            return [{"자료ID": aid.strip()} for aid in selector.id_list]
        return []

    # ── core crawl loop ──────────────────────────────────────────────

    def _do_crawl(
        self,
        api_articles: List[dict],
        slug: str,
        mode: str,
        raw_request: dict,
        normalized_request: dict,
        config: FathomConfig,
        limit: Optional[int],
    ) -> CrawlResult:
        if limit and limit < len(api_articles):
            api_articles = api_articles[:limit]

        db_root = str(config.resolved_db_root())
        writer = BundleWriter(db_root=db_root, source="munzip", slug=slug)
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

        task_id = f"itkc-{mode}-001"
        pb.add_task(
            task_id=task_id,
            db="itkc",
            mode=mode,
            raw_request=raw_request,
            normalized_request=normalized_request,
        )

        total = len(api_articles)
        succeeded = 0
        failed = 0
        write_lock = Lock()

        def _fetch_one(api_art: dict) -> dict:
            data_id = api_art.get("자료ID", "")
            try:
                content = fetch_article_content(data_id)
                is_failure = content.get("original") == "[크롤링 실패]"
                if is_failure:
                    return {"ok": False, "api": api_art, "error": content.get("error", "Unknown")}
                return {"ok": True, "api": api_art, "content": content}
            except Exception as exc:
                return {"ok": False, "api": api_art, "error": str(exc)}

        workers = min(4, max(1, total))
        if total > 0:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(_fetch_one, a): a for a in api_articles}
                for fut in as_completed(futures):
                    res = fut.result()
                    with write_lock:
                        if res["ok"]:
                            article = _convert_to_v31(res["content"], res["api"])
                            article = format_article(article, "munzip")
                            writer.write_article(article)
                            succeeded += 1
                        else:
                            api_art = res["api"]
                            rec = format_failed(
                                id=api_art.get("자료ID", "unknown"),
                                url=f"{WEB_BASE}/dir/node?dataId={api_art.get('자료ID', '')}",
                                error=res.get("error", "Unknown"),
                            )
                            writer.write_failed(rec)
                            failed += 1
                    # Rate limiting between fetches
                    time.sleep(0.3)

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
            "📙 문집 크롤링 완료",
            f"   총 대상: {result.total}건",
            f"   성공: {result.succeeded}건",
        ]
        if result.failed:
            lines.append(f"   실패: {result.failed}건")
        lines.append(f"   번들: {result.bundle_path}")
        return "\n".join(lines)
