import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from unittest.mock import patch, MagicMock, PropertyMock
from engine.selector import parse_selector, Selector
from engine.config import FathomConfig
from dbs.base import CountResult, CrawlResult
from dbs.sjw.adapter import SJWAdapter, _convert_to_v31, _normalise_search_entry, _normalise_browse_entry

SJW_BASE = "https://sjw.history.go.kr"


# ===== TestConversion =====

class TestConversion:
    def test_basic_conversion(self):
        raw_content = {
            "title": "승정원일기 기사",
            "translation": "번역 내용입니다.",
            "original": "原文 內容",
            "has_translation": True,
            "itkc_data_id": "ITKC_SJ_00001",
            "source_info": {
                "reign": "현종",
                "year": 1,
                "month": 1,
                "day": 1,
                "ganzhi": "갑자",
                "article_num": 1,
                "total_articles": 5,
                "western_year": 1660,
                "chinese_era": "順治 17",
                "book_num": 1,
                "book_num_talcho": 1,
                "source_info": "원천정보",
            },
        }
        entry = {
            "id": "sjw_00010101_001",
            "title": "Entry Title",
        }

        article = _convert_to_v31(raw_content, entry)

        assert article["schema_version"] == "3.1"
        assert article["source"] == "sjw"
        assert article["id"] == "sjw_00010101_001"
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
            "has_translation": False,
            "itkc_data_id": "",
            "source_info": {
                "reign": "인조",
                "year": 10,
                "month": 5,
                "day": 15,
                "ganzhi": "을축",
                "article_num": 3,
                "total_articles": 10,
            },
        }
        entry = {"id": "sjw_injo_10_05_15_003", "title": ""}

        article = _convert_to_v31(raw_content, entry)

        assert article["metadata"]["date"]["reign"] == "인조"
        assert article["metadata"]["date"]["year"] == 10
        assert article["metadata"]["date"]["month"] == 5
        assert article["metadata"]["date"]["day"] == 15
        assert article["metadata"]["date"]["ganzhi"] == "을축"
        assert article["metadata"]["date"]["article_num"] == 3
        assert article["metadata"]["date"]["total_articles"] == 10

    def test_paragraphs_split(self):
        raw_content = {
            "title": "Test",
            "translation": "First para\n\nSecond para\n\nThird para",
            "original": "원문 첫단락\n\n원문 둘째단락",
            "has_translation": True,
            "itkc_data_id": "",
            "source_info": {},
        }
        entry = {"id": "test_001"}

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
            "has_translation": False,
            "itkc_data_id": "",
            "source_info": {},
        }
        entry = {"id": "test_001"}

        article = _convert_to_v31(raw_content, entry)

        assert article["translation"]["paragraphs"] == []
        assert article["original"]["paragraphs"] == []
        assert article["metadata"]["title"] == ""

    def test_has_translation_flag(self):
        raw_true = {"translation": "Valid", "original": "Text", "title": "", "has_translation": True, "itkc_data_id": "", "source_info": {}}
        raw_false = {"translation": "", "original": "Text", "title": "", "has_translation": False, "itkc_data_id": "", "source_info": {}}
        entry = {"id": "test_001"}

        assert _convert_to_v31(raw_true, entry)["has_translation"] is True
        assert _convert_to_v31(raw_false, entry)["has_translation"] is False

    def test_appendix_structure(self):
        raw_content = {"title": "", "translation": "", "original": "", "has_translation": False, "itkc_data_id": "", "source_info": {}}
        entry = {"id": "test_001"}

        article = _convert_to_v31(raw_content, entry)

        assert "person_annotations" in article["appendix"]
        assert "day_total_articles" in article["appendix"]


# ===== TestCapabilities =====

class TestCapabilities:
    def test_db_id(self):
        adapter = SJWAdapter()
        assert adapter.db_id == "sjw"

    def test_capabilities_selectors(self):
        adapter = SJWAdapter()
        caps = adapter.capabilities()
        assert "selectors" in caps
        assert set(caps["selectors"]) == {"query", "time_range", "work_scope", "ids"}

    def test_capabilities_count_support(self):
        adapter = SJWAdapter()
        caps = adapter.capabilities()
        assert "count_support" in caps
        assert caps["count_support"]["query"] == "exact"


# ===== TestCount =====

class TestCount:
    @patch('dbs.sjw.adapter.SjwSearcher')
    def test_count_query(self, mock_searcher_cls):
        mock_instance = MagicMock()
        mock_instance.search.return_value = (523, [], None)
        mock_searcher_cls.return_value = mock_instance

        adapter = SJWAdapter()
        selector = parse_selector({"type": "query", "keywords": "송시열"})
        result = adapter.count(selector)

        assert result.kind == "exact"
        assert result.count == 523
        mock_instance.setup_session.assert_called_once()
        mock_instance.close.assert_called_once()

    def test_count_ids(self):
        adapter = SJWAdapter()
        selector = parse_selector({"type": "ids", "id_list": ["sjw_001", "sjw_002", "sjw_003"]})
        result = adapter.count(selector)

        assert result.kind == "exact"
        assert result.count == 3

    def test_count_unsupported(self):
        adapter = SJWAdapter()
        selector = parse_selector({"type": "time_range", "reign": "인조", "year_from": 1, "year_to": 5})
        result = adapter.count(selector)

        assert result.kind == "unknown"
        assert "전체 열람 후에만" in result.message


# ===== TestCrawl =====

class TestCrawl:
    @patch('dbs.sjw.adapter.BundleWriter')
    @patch('dbs.sjw.adapter.create_session')
    @patch('dbs.sjw.adapter.fetch_article')
    @patch('dbs.sjw.adapter.SjwSearcher')
    def test_crawl_query_pipeline(self, mock_searcher_cls, mock_fetch, mock_session, mock_writer_cls, tmp_path):
        # Setup searcher mock
        mock_searcher = MagicMock()
        mock_searcher.search_and_collect.return_value = {
            "entries": [
                {"id": "sjw_001", "url": "http://test1", "title": "Title 1"},
                {"id": "sjw_002", "url": "http://test2", "title": "Title 2"},
            ]
        }
        mock_searcher_cls.return_value = mock_searcher

        # Setup fetch mock
        mock_fetch.return_value = {
            "title": "Article",
            "translation": "Translation",
            "original": "Original",
            "has_translation": True,
            "itkc_data_id": "",
            "source_info": {},
        }

        # Setup writer mock
        mock_writer = MagicMock()
        mock_writer.open.return_value = tmp_path / "bndl_20260213-1430__test__src-sjw"
        mock_writer.close.return_value = {
            "succeeded": 2,
            "failed": 0,
            "articles_path": str(tmp_path / "articles.jsonl"),
            "failed_path": str(tmp_path / "failed.jsonl"),
        }
        mock_writer_cls.return_value = mock_writer

        # Create bundle path
        bundle_path = tmp_path / "bndl_20260213-1430__test__src-sjw"
        bundle_path.mkdir()

        config = FathomConfig(db_root=str(tmp_path))
        adapter = SJWAdapter()
        selector = parse_selector({"type": "query", "keywords": "송시열"})

        result = adapter.crawl(selector, config)

        assert result.total == 2
        assert result.succeeded == 2
        assert result.failed == 0
        assert result.bundle_path == bundle_path

    @patch('dbs.sjw.adapter.BundleWriter')
    @patch('dbs.sjw.adapter.create_session')
    @patch('dbs.sjw.adapter.fetch_article')
    def test_crawl_ids_pipeline(self, mock_fetch, mock_session, mock_writer_cls, tmp_path):
        mock_fetch.return_value = {
            "title": "Article",
            "translation": "Translation",
            "original": "Original",
            "has_translation": True,
            "itkc_data_id": "",
            "source_info": {},
        }

        mock_writer = MagicMock()
        bundle_path = tmp_path / "bndl_20260213-1430__test__src-sjw"
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
        adapter = SJWAdapter()
        selector = parse_selector({"type": "ids", "id_list": ["sjw_001", "sjw_002"]})

        result = adapter.crawl(selector, config)

        assert result.total == 2
        assert result.succeeded == 2

    @patch('dbs.sjw.adapter.BundleWriter')
    @patch('dbs.sjw.adapter.create_session')
    @patch('dbs.sjw.adapter.fetch_article')
    @patch('dbs.sjw.adapter.browse_collect_entries')
    def test_crawl_time_range_pipeline(self, mock_browse, mock_fetch, mock_session, mock_writer_cls, tmp_path):
        mock_browse.return_value = [
            {"id": "sjw_001", "url": "http://test1", "title": "Title 1"},
            {"id": "sjw_002", "url": "http://test2", "title": "Title 2"},
        ]

        mock_fetch.return_value = {
            "title": "Article",
            "translation": "Translation",
            "original": "Original",
            "has_translation": True,
            "itkc_data_id": "",
            "source_info": {},
        }

        mock_writer = MagicMock()
        bundle_path = tmp_path / "bndl_20260213-1430__test__src-sjw"
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
        adapter = SJWAdapter()
        selector = parse_selector({"type": "time_range", "reign": "인조", "year_from": 1, "year_to": 5})

        result = adapter.crawl(selector, config)

        assert result.total == 2
        assert result.succeeded == 2

    @patch('dbs.sjw.adapter.BundleWriter')
    @patch('dbs.sjw.adapter.create_session')
    @patch('dbs.sjw.adapter.fetch_article')
    @patch('dbs.sjw.adapter.SjwSearcher')
    def test_crawl_with_limit(self, mock_searcher_cls, mock_fetch, mock_session, mock_writer_cls, tmp_path):
        mock_searcher = MagicMock()
        mock_searcher.search_and_collect.return_value = {
            "entries": [{"id": f"sjw_{i:03d}", "url": f"http://test{i}", "title": f"Title {i}"} for i in range(10)]
        }
        mock_searcher_cls.return_value = mock_searcher

        mock_fetch.return_value = {
            "title": "Article",
            "translation": "Translation",
            "original": "Original",
            "has_translation": True,
            "itkc_data_id": "",
            "source_info": {},
        }

        mock_writer = MagicMock()
        bundle_path = tmp_path / "bndl_20260213-1430__test__src-sjw"
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
        adapter = SJWAdapter()
        selector = parse_selector({"type": "query", "keywords": "송시열"})

        result = adapter.crawl(selector, config, limit=3)

        assert result.total == 3
        assert mock_fetch.call_count == 3

    @patch('dbs.sjw.adapter.BundleWriter')
    @patch('dbs.sjw.adapter.create_session')
    @patch('dbs.sjw.adapter.fetch_article')
    @patch('dbs.sjw.adapter.SjwSearcher')
    def test_crawl_handles_failures(self, mock_searcher_cls, mock_fetch, mock_session, mock_writer_cls, tmp_path):
        mock_searcher = MagicMock()
        mock_searcher.search_and_collect.return_value = {
            "entries": [
                {"id": "sjw_001", "url": "http://test1", "title": "Title 1"},
                {"id": "sjw_002", "url": "http://test2", "title": "Title 2"},
            ]
        }
        mock_searcher_cls.return_value = mock_searcher

        # First succeeds, second fails
        mock_fetch.side_effect = [
            {"title": "Article", "translation": "Translation", "original": "Original", "has_translation": True, "itkc_data_id": "", "source_info": {}},
            {"title": "Failed", "original": "[크롤링 실패]", "error": "Connection timeout"},
        ]

        mock_writer = MagicMock()
        bundle_path = tmp_path / "bndl_20260213-1430__test__src-sjw"
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
        adapter = SJWAdapter()
        selector = parse_selector({"type": "query", "keywords": "송시열"})

        result = adapter.crawl(selector, config)

        assert result.succeeded == 1
        assert result.failed == 1

    @patch('dbs.sjw.adapter.BundleWriter')
    @patch('dbs.sjw.adapter.SjwSearcher')
    def test_crawl_empty_entries(self, mock_searcher_cls, mock_writer_cls, tmp_path):
        mock_searcher = MagicMock()
        mock_searcher.search_and_collect.return_value = {"entries": []}
        mock_searcher_cls.return_value = mock_searcher

        mock_writer = MagicMock()
        bundle_path = tmp_path / "bndl_20260213-1430__test__src-sjw"
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
        adapter = SJWAdapter()
        selector = parse_selector({"type": "query", "keywords": "nonexistent_keyword_xyz"})

        result = adapter.crawl(selector, config)

        assert result.total == 0
        assert result.succeeded == 0
        assert result.failed == 0


# ===== SJW-specific tests =====

class TestSJWSpecific:
    def test_normalise_search_entry(self):
        raw_entry = {
            "id": "sjw_00010101_001",
            "url": "http://old-url",
            "title": "승정원일기 기사",
        }

        normalized = _normalise_search_entry(raw_entry)

        assert normalized["id"] == "sjw_00010101_001"
        assert normalized["title"] == "승정원일기 기사"
        assert normalized["url"] == "http://old-url"

    def test_normalise_browse_entry(self):
        raw_entry = {
            "id": "sjw_00010101_001",
            "title": "승정원일기 기사",
            "url": "http://browse-url",
        }

        normalized = _normalise_browse_entry(raw_entry)

        assert normalized["id"] == "sjw_00010101_001"
        assert normalized["title"] == "승정원일기 기사"
        assert normalized["url"] == "http://browse-url"

    def test_resolve_ids_constructs_url(self):
        adapter = SJWAdapter()
        selector = parse_selector({"type": "ids", "id_list": ["sjw_001", "sjw_002"]})

        entries = adapter._resolve_ids(selector)

        assert len(entries) == 2
        assert entries[0]["id"] == "sjw_001"
        assert f"{SJW_BASE}/id/sjw_001" in entries[0]["url"]
        assert entries[1]["id"] == "sjw_002"
        assert f"{SJW_BASE}/id/sjw_002" in entries[1]["url"]

    def test_format_report(self, tmp_path):
        adapter = SJWAdapter()
        result = CrawlResult(
            bundle_path=tmp_path / "bndl_test",
            total=200,
            succeeded=195,
            failed=5,
            articles_path=tmp_path / "articles.jsonl",
            failed_path=tmp_path / "failed.jsonl",
        )

        report = adapter.format_report(result)

        assert "승정원일기 크롤링 완료" in report
        assert "200건" in report
        assert "195건" in report
        assert "5건" in report
