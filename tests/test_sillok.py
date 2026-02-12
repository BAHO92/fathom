import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from unittest.mock import patch, MagicMock, PropertyMock
from engine.selector import parse_selector, Selector
from engine.config import FathomConfig
from dbs.base import CountResult, CrawlResult
from dbs.sillok.adapter import SillokAdapter, _convert_to_v31, _resolve_tab


# ===== TestConversion =====

class TestConversion:
    def test_basic_conversion(self):
        raw_content = {
            "title": "송시열 관련 기사",
            "translation": "번역 내용입니다.",
            "original": "原文 內容",
            "footnotes": {},
            "category": [],
            "date_info": {},
            "page_info": "",
        }
        entry = {
            "id": "kwa_10101010_001",
            "url": "https://sillok.history.go.kr/id/kwa_10101010_001",
            "title": "Entry Title",
            "volume_info": "현종실록 1권",
            "date": {"reign": "현종", "year": 1, "month": 1, "day": 1, "ganzhi": "갑자", "article_num": 1},
        }

        article = _convert_to_v31(raw_content, entry)

        assert article["schema_version"] == "3.1"
        assert article["source"] == "sillok"
        assert article["id"] == "kwa_10101010_001"
        assert "metadata" in article
        assert "translation" in article
        assert "original" in article
        assert "crawled_at" in article
        assert "appendix" in article

    def test_date_extraction(self):
        raw_content = {
            "title": "Test",
            "translation": "Text",
            "original": "Text",
            "date_info": {"ganzhi": "을축", "article_num": 3},
            "footnotes": {},
            "category": [],
            "page_info": "",
        }
        entry = {
            "id": "test_001",
            "url": "http://test",
            "date": {"reign": "세종", "year": 10, "month": 5, "day": 15, "ganzhi": "갑자", "article_num": 1},
        }

        article = _convert_to_v31(raw_content, entry)

        # Should prefer page-extracted date_info fields
        assert article["metadata"]["date"]["reign"] == "세종"
        assert article["metadata"]["date"]["year"] == 10
        assert article["metadata"]["date"]["ganzhi"] == "을축"
        assert article["metadata"]["date"]["article_num"] == 3

    def test_paragraphs_split(self):
        raw_content = {
            "title": "Test",
            "translation": "First para\n\nSecond para\n\nThird para",
            "original": "원문 첫단락\n\n원문 둘째단락",
            "footnotes": {},
            "category": [],
            "date_info": {},
            "page_info": "",
        }
        entry = {"id": "test_001", "url": "http://test", "date": {}}

        article = _convert_to_v31(raw_content, entry)

        assert len(article["translation"]["paragraphs"]) == 3
        assert article["translation"]["paragraphs"][0] == "First para"
        assert len(article["original"]["paragraphs"]) == 2
        assert article["original"]["paragraphs"][1] == "원문 둘째단락"

    def test_empty_fields(self):
        raw_content = {
            "title": "",
            "translation": "",
            "original": "",
            "footnotes": {},
            "category": [],
            "date_info": {},
            "page_info": "",
        }
        entry = {"id": "test_001", "url": "http://test"}

        article = _convert_to_v31(raw_content, entry)

        assert article["translation"]["paragraphs"] == []
        assert article["original"]["paragraphs"] == []
        assert article["footnotes"] == []
        assert article["metadata"]["title"] == ""

    def test_has_translation_flag(self):
        raw_true = {"translation": "Valid translation", "original": "Text", "title": "", "footnotes": {}, "category": [], "date_info": {}, "page_info": ""}
        raw_false = {"translation": "", "original": "Text", "title": "", "footnotes": {}, "category": [], "date_info": {}, "page_info": ""}
        raw_fail = {"translation": "[크롤링 실패]", "original": "Text", "title": "", "footnotes": {}, "category": [], "date_info": {}, "page_info": ""}
        entry = {"id": "test_001", "url": "http://test"}

        assert _convert_to_v31(raw_true, entry)["has_translation"] is True
        assert _convert_to_v31(raw_false, entry)["has_translation"] is False
        assert _convert_to_v31(raw_fail, entry)["has_translation"] is False

    def test_appendix_structure(self):
        raw_content = {"title": "", "translation": "", "original": "", "footnotes": {}, "category": [], "date_info": {}, "page_info": ""}
        entry = {"id": "test_001", "url": "http://test"}

        article = _convert_to_v31(raw_content, entry)

        assert "day_articles" in article["appendix"]
        assert "prev_article_id" in article["appendix"]
        assert "next_article_id" in article["appendix"]
        assert "place_annotations" in article["appendix"]
        assert "book_annotations" in article["appendix"]


# ===== TestCapabilities =====

class TestCapabilities:
    def test_db_id(self):
        adapter = SillokAdapter()
        assert adapter.db_id == "sillok"

    def test_capabilities_selectors(self):
        adapter = SillokAdapter()
        caps = adapter.capabilities()
        assert "selectors" in caps
        assert set(caps["selectors"]) == {"query", "work_scope", "ids"}

    def test_capabilities_count_support(self):
        adapter = SillokAdapter()
        caps = adapter.capabilities()
        assert "count_support" in caps
        assert caps["count_support"]["query"] == "exact"


# ===== TestCount =====

class TestCount:
    @patch('dbs.sillok.adapter.SillokSearcher')
    def test_count_query(self, mock_searcher_cls):
        mock_instance = MagicMock()
        mock_instance.count_only.return_value = 412
        mock_searcher_cls.return_value = mock_instance

        adapter = SillokAdapter()
        selector = parse_selector({"type": "query", "keywords": "송시열"})
        result = adapter.count(selector)

        assert result.kind == "exact"
        assert result.count == 412
        mock_instance.setup_session.assert_called_once()
        mock_instance.close.assert_called_once()

    @patch('dbs.sillok.adapter.parse_input_file')
    def test_count_ids(self, mock_parse):
        mock_parse.return_value = [{"id": "a"}, {"id": "b"}, {"id": "c"}]

        adapter = SillokAdapter()
        selector = parse_selector({"type": "ids", "source_file": "/tmp/ids.txt"})
        result = adapter.count(selector)

        assert result.kind == "exact"
        assert result.count == 3

    def test_count_unsupported(self):
        adapter = SillokAdapter()
        selector = parse_selector({"type": "work_scope", "work_kind": "reign", "work_id": "hyeonjong"})
        result = adapter.count(selector)

        assert result.kind == "unknown"
        assert "지원하지 않습니다" in result.message


# ===== TestCrawl =====

class TestCrawl:
    @patch('dbs.sillok.adapter.BundleWriter')
    @patch('dbs.sillok.adapter.create_session')
    @patch('dbs.sillok.adapter.fetch_article')
    @patch('dbs.sillok.adapter.SillokSearcher')
    def test_crawl_query_pipeline(self, mock_searcher_cls, mock_fetch, mock_session, mock_writer_cls, tmp_path):
        # Setup searcher mock
        mock_searcher = MagicMock()
        mock_searcher.search_multiple_keywords.return_value = {
            "entries": [
                {"id": "test_001", "url": "http://test1", "title": "Title 1", "volume": "현종실록 1권", "date": "현종 1년 1월 1일"},
                {"id": "test_002", "url": "http://test2", "title": "Title 2", "volume": "현종실록 2권", "date": "현종 2년 2월 2일"},
            ]
        }
        mock_searcher_cls.return_value = mock_searcher

        # Setup fetch mock
        mock_fetch.return_value = {
            "title": "Article",
            "translation": "Translation",
            "original": "Original",
            "footnotes": {},
            "category": [],
            "date_info": {},
            "page_info": "",
        }

        # Setup writer mock
        mock_writer = MagicMock()
        mock_writer.open.return_value = tmp_path / "bndl_20260213-1430__test__src-sillok"
        mock_writer.close.return_value = {
            "succeeded": 2,
            "failed": 0,
            "articles_path": str(tmp_path / "articles.jsonl"),
            "failed_path": str(tmp_path / "failed.jsonl"),
        }
        mock_writer_cls.return_value = mock_writer

        # Create bundle path
        bundle_path = tmp_path / "bndl_20260213-1430__test__src-sillok"
        bundle_path.mkdir()

        config = FathomConfig(db_root=str(tmp_path))
        adapter = SillokAdapter()
        selector = parse_selector({"type": "query", "keywords": "송시열"})

        result = adapter.crawl(selector, config)

        assert result.total == 2
        assert result.succeeded == 2
        assert result.failed == 0
        assert result.bundle_path == bundle_path

    @patch('dbs.sillok.adapter.BundleWriter')
    @patch('dbs.sillok.adapter.create_session')
    @patch('dbs.sillok.adapter.fetch_article')
    def test_crawl_ids_pipeline(self, mock_fetch, mock_session, mock_writer_cls, tmp_path):
        mock_fetch.return_value = {
            "title": "Article",
            "translation": "Translation",
            "original": "Original",
            "footnotes": {},
            "category": [],
            "date_info": {},
            "page_info": "",
        }

        mock_writer = MagicMock()
        bundle_path = tmp_path / "bndl_20260213-1430__test__src-sillok"
        bundle_path.mkdir()
        mock_writer.open.return_value = bundle_path
        mock_writer.close.return_value = {
            "succeeded": 2,
            "failed": 0,
            "articles_path": str(tmp_path / "articles.jsonl"),
            "failed_path": str(tmp_path / "failed.jsonl"),
        }
        mock_writer_cls.return_value = mock_writer

        config = FathomConfig(db_root=str(tmp_path))
        adapter = SillokAdapter()
        selector = parse_selector({"type": "ids", "id_list": ["kwa_10101010_001", "kwa_10101010_002"]})

        result = adapter.crawl(selector, config)

        assert result.total == 2
        assert result.succeeded == 2

    @patch('dbs.sillok.adapter.BundleWriter')
    @patch('dbs.sillok.adapter.create_session')
    @patch('dbs.sillok.adapter.fetch_article')
    @patch('dbs.sillok.adapter.SillokSearcher')
    def test_crawl_with_limit(self, mock_searcher_cls, mock_fetch, mock_session, mock_writer_cls, tmp_path):
        mock_searcher = MagicMock()
        mock_searcher.search_multiple_keywords.return_value = {
            "entries": [
                {"id": f"test_{i:03d}", "url": f"http://test{i}", "title": f"Title {i}", "volume": "현종실록 1권", "date": "현종 1년 1월 1일"}
                for i in range(10)
            ]
        }
        mock_searcher_cls.return_value = mock_searcher

        mock_fetch.return_value = {
            "title": "Article",
            "translation": "Translation",
            "original": "Original",
            "footnotes": {},
            "category": [],
            "date_info": {},
            "page_info": "",
        }

        mock_writer = MagicMock()
        bundle_path = tmp_path / "bndl_20260213-1430__test__src-sillok"
        bundle_path.mkdir()
        mock_writer.open.return_value = bundle_path
        mock_writer.close.return_value = {
            "succeeded": 3,
            "failed": 0,
            "articles_path": str(tmp_path / "articles.jsonl"),
            "failed_path": str(tmp_path / "failed.jsonl"),
        }
        mock_writer_cls.return_value = mock_writer

        config = FathomConfig(db_root=str(tmp_path))
        adapter = SillokAdapter()
        selector = parse_selector({"type": "query", "keywords": "송시열"})

        result = adapter.crawl(selector, config, limit=3)

        assert result.total == 3
        assert mock_fetch.call_count == 3

    @patch('dbs.sillok.adapter.BundleWriter')
    @patch('dbs.sillok.adapter.create_session')
    @patch('dbs.sillok.adapter.fetch_article')
    @patch('dbs.sillok.adapter.SillokSearcher')
    def test_crawl_handles_failures(self, mock_searcher_cls, mock_fetch, mock_session, mock_writer_cls, tmp_path):
        mock_searcher = MagicMock()
        mock_searcher.search_multiple_keywords.return_value = {
            "entries": [
                {"id": "test_001", "url": "http://test1", "title": "Title 1", "volume": "현종실록 1권", "date": "현종 1년 1월 1일"},
                {"id": "test_002", "url": "http://test2", "title": "Title 2", "volume": "현종실록 2권", "date": "현종 2년 2월 2일"},
            ]
        }
        mock_searcher_cls.return_value = mock_searcher

        # First succeeds, second fails
        mock_fetch.side_effect = [
            {"title": "Article", "translation": "Translation", "original": "Original", "footnotes": {}, "category": [], "date_info": {}, "page_info": ""},
            {"title": "Failed", "translation": "[크롤링 실패]", "error": "Connection timeout"},
        ]

        mock_writer = MagicMock()
        bundle_path = tmp_path / "bndl_20260213-1430__test__src-sillok"
        bundle_path.mkdir()
        mock_writer.open.return_value = bundle_path
        mock_writer.close.return_value = {
            "succeeded": 1,
            "failed": 1,
            "articles_path": str(tmp_path / "articles.jsonl"),
            "failed_path": str(tmp_path / "failed.jsonl"),
        }
        mock_writer_cls.return_value = mock_writer

        config = FathomConfig(db_root=str(tmp_path))
        adapter = SillokAdapter()
        selector = parse_selector({"type": "query", "keywords": "송시열"})

        result = adapter.crawl(selector, config)

        assert result.succeeded == 1
        assert result.failed == 1

    @patch('dbs.sillok.adapter.BundleWriter')
    @patch('dbs.sillok.adapter.SillokSearcher')
    def test_crawl_empty_entries(self, mock_searcher_cls, mock_writer_cls, tmp_path):
        mock_searcher = MagicMock()
        mock_searcher.search_multiple_keywords.return_value = {"entries": []}
        mock_searcher_cls.return_value = mock_searcher

        mock_writer = MagicMock()
        bundle_path = tmp_path / "bndl_20260213-1430__test__src-sillok"
        bundle_path.mkdir()
        mock_writer.open.return_value = bundle_path
        mock_writer.close.return_value = {
            "succeeded": 0,
            "failed": 0,
            "articles_path": str(tmp_path / "articles.jsonl"),
            "failed_path": str(tmp_path / "failed.jsonl"),
        }
        mock_writer_cls.return_value = mock_writer

        config = FathomConfig(db_root=str(tmp_path))
        adapter = SillokAdapter()
        selector = parse_selector({"type": "query", "keywords": "nonexistent_keyword_xyz"})

        result = adapter.crawl(selector, config)

        assert result.total == 0
        assert result.succeeded == 0
        assert result.failed == 0


# ===== Sillok-specific tests =====

class TestSillokSpecific:
    def test_resolve_tab(self):
        assert _resolve_tab("translation") == "k"
        assert _resolve_tab("original") == "w"
        assert _resolve_tab(None) == "w"
        assert _resolve_tab("k") == "k"

    @patch('dbs.sillok.adapter.parse_date_info')
    def test_normalise_search_entry(self, mock_parse_date):
        from dbs.sillok.adapter import _normalise_search_entry

        mock_parse_date.return_value = {"reign": "현종", "year": 1, "month": 1, "day": 1, "ganzhi": "갑자", "article_num": 1}

        raw_entry = {
            "id": "kwa_10101010_001",
            "url": "https://sillok.history.go.kr/id/kwa_10101010_001",
            "title": "송시열 관련 기사",
            "volume": "현종실록 1권",
            "date": "현종 1년 1월 1일",
        }

        normalized = _normalise_search_entry(raw_entry)

        assert normalized["id"] == "kwa_10101010_001"
        assert normalized["url"] == "https://sillok.history.go.kr/id/kwa_10101010_001"
        assert normalized["title"] == "송시열 관련 기사"
        assert normalized["volume_info"] == "현종실록 1권"
        assert "date" in normalized

    def test_work_scope_returns_empty(self):
        adapter = SillokAdapter()
        selector = parse_selector({"type": "work_scope", "work_kind": "reign", "work_id": "hyeonjong"})

        entries = adapter._resolve_work_scope(selector)

        assert entries == []

    def test_format_report(self, tmp_path):
        adapter = SillokAdapter()
        result = CrawlResult(
            bundle_path=tmp_path / "bndl_test",
            total=100,
            succeeded=98,
            failed=2,
            articles_path=tmp_path / "articles.jsonl",
            failed_path=tmp_path / "failed.jsonl",
        )

        report = adapter.format_report(result)

        assert "실록 크롤링 완료" in report
        assert "100건" in report
        assert "98건" in report
        assert "2건" in report
