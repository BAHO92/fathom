import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from unittest.mock import patch, MagicMock, PropertyMock
from engine.selector import parse_selector, Selector
from engine.config import FathomConfig
from dbs.base import CountResult, CrawlResult
from dbs.itkc.adapter import ITKCAdapter, _convert_to_v31

WEB_BASE = "https://db.itkc.or.kr"


# ===== TestConversion =====

class TestConversion:
    def test_basic_conversion(self):
        content = {
            "title": "문집 기사",
            "title_ko": "문집 기사 번역",
            "translation": "번역 내용입니다.",
            "original": "原文 內容",
            "has_translation": True,
        }
        api_article = {
            "자료ID": "ITKC_MO_0367A_0010_010_0010",
            "DCI_s": "ITKC_MO_0367A_DCI",
            "기사명": "API Title",
            "서명": "栗谷全書",
            "권차명": "권1",
            "문체명": "서",
            "문체분류": "기록류",
            "저자": "이이(李珥, 1536~1584)",
            "저자생년": "1536",
            "저자몰년": "1584",
            "집수번호": "1",
            "자료구분": "문집",
            "간행기간": "조선",
            "간행년": "1814",
            "간행처": "전주",
            "역자": "홍길동",
        }

        article = _convert_to_v31(content, api_article)

        assert article["schema_version"] == "3.1"
        assert article["source"] == "munzip"
        assert article["id"] == "ITKC_MO_0367A_0010_010_0010"
        assert "metadata" in article
        assert "translation" in article
        assert "original" in article
        assert "crawled_at" in article
        assert "appendix" in article

    def test_date_extraction(self):
        content = {
            "title": "Test",
            "title_ko": "테스트",
            "translation": "Text",
            "original": "Text",
            "has_translation": True,
        }
        api_article = {
            "자료ID": "ITKC_MO_0001A_0001_001_0001",
            "기사명": "Title",
            "서명": "書名",
            "저자": "작자미상",
        }

        article = _convert_to_v31(content, api_article)

        assert article["metadata"]["title"] == "Test"
        assert article["metadata"]["title_ko"] == "테스트"
        assert article["metadata"]["seo_myeong"] == "書名"

    def test_paragraphs_split(self):
        content = {
            "title": "Test",
            "title_ko": "테스트",
            "translation": "First para\n\nSecond para\n\nThird para",
            "original": "원문 첫단락\n\n원문 둘째단락",
            "has_translation": True,
        }
        api_article = {
            "자료ID": "ITKC_MO_0001A_0001_001_0001",
            "기사명": "Title",
            "서명": "書",
            "저자": "作者",
        }

        article = _convert_to_v31(content, api_article)

        assert len(article["translation"]["paragraphs"]) == 3
        assert article["translation"]["paragraphs"][0]["text"] == "First para"
        assert len(article["original"]["sections"]) == 1
        assert len(article["original"]["sections"][0]["lines"]) == 2
        assert article["original"]["sections"][0]["lines"][1] == "원문 둘째단락"

    def test_empty_fields(self):
        content = {
            "title": "",
            "title_ko": None,
            "translation": "",
            "original": "",
            "has_translation": False,
        }
        api_article = {
            "자료ID": "ITKC_MO_0001A_0001_001_0001",
            "기사명": "",
            "서명": "",
            "저자": "",
        }

        article = _convert_to_v31(content, api_article)

        assert article["translation"]["paragraphs"] == []
        assert article["original"]["sections"] == []
        assert article["metadata"]["title"] == ""

    def test_has_translation_flag(self):
        content_true = {"translation": "Valid", "original": "Text", "title": "", "title_ko": None, "has_translation": True}
        content_false = {"translation": "", "original": "Text", "title": "", "title_ko": None, "has_translation": False}
        api_article = {"자료ID": "test_001", "기사명": "", "서명": "", "저자": ""}

        assert _convert_to_v31(content_true, api_article)["has_translation"] is True
        assert _convert_to_v31(content_false, api_article)["has_translation"] is False

    def test_appendix_structure(self):
        content = {"title": "", "title_ko": None, "translation": "", "original": "", "has_translation": False}
        api_article = {"자료ID": "test_001", "기사명": "", "서명": "", "저자": ""}

        article = _convert_to_v31(content, api_article)

        assert "page_markers" in article["appendix"]
        assert "indent_levels" in article["appendix"]


# ===== TestCapabilities =====

class TestCapabilities:
    def test_db_id(self):
        adapter = ITKCAdapter()
        assert adapter.db_id == "itkc"

    def test_capabilities_selectors(self):
        adapter = ITKCAdapter()
        caps = adapter.capabilities()
        assert "selectors" in caps
        assert set(caps["selectors"]) == {"query", "work_scope", "ids"}

    def test_capabilities_count_support(self):
        adapter = ITKCAdapter()
        caps = adapter.capabilities()
        assert "count_support" in caps
        assert caps["count_support"]["query"] == "exact"
        assert caps["count_support"]["work_scope"] == "exact"


# ===== TestCount =====

class TestCount:
    @patch('dbs.itkc.adapter.fetch_api')
    @patch('dbs.itkc.adapter.get_sec_id_for_collection')
    def test_count_query(self, mock_get_sec, mock_fetch_api):
        mock_get_sec.return_value = "MO_0367A_BD"
        mock_fetch_api.return_value = {"total_count": 234, "docs": []}

        adapter = ITKCAdapter()
        selector = parse_selector({"type": "query", "keywords": "송시열", "work_id": "ITKC_MO_0367A"})
        result = adapter.count(selector)

        assert result.kind == "exact"
        assert result.count == 234
        mock_fetch_api.assert_called_once()

    @patch('dbs.itkc.adapter.fetch_api')
    @patch('dbs.itkc.adapter.get_sec_id_for_collection')
    def test_count_work_scope(self, mock_get_sec, mock_fetch_api):
        mock_get_sec.return_value = "MO_0367A_GS"
        mock_fetch_api.return_value = {"total_count": 1523, "docs": []}

        adapter = ITKCAdapter()
        selector = parse_selector({"type": "work_scope", "work_kind": "collection", "work_id": "ITKC_MO_0367A"})
        result = adapter.count(selector)

        assert result.kind == "exact"
        assert result.count == 1523

    def test_count_ids(self):
        adapter = ITKCAdapter()
        selector = parse_selector({"type": "ids", "id_list": ["ITKC_MO_001", "ITKC_MO_002", "ITKC_MO_003"]})
        result = adapter.count(selector)

        assert result.kind == "exact"
        assert result.count == 3


# ===== TestCrawl =====

class TestCrawl:
    @patch('dbs.itkc.adapter.BundleWriter')
    @patch('dbs.itkc.adapter.fetch_article_content')
    @patch('dbs.itkc.adapter.fetch_article_list_search')
    def test_crawl_query_pipeline(self, mock_search, mock_fetch_content, mock_writer_cls, tmp_path):
        # Setup search mock
        mock_search.return_value = [
            {"자료ID": "ITKC_MO_001", "기사명": "Title 1", "서명": "書1", "저자": "作者1"},
            {"자료ID": "ITKC_MO_002", "기사명": "Title 2", "서명": "書2", "저자": "作者2"},
        ]

        # Setup fetch mock
        mock_fetch_content.return_value = {
            "title": "Article",
            "title_ko": "기사",
            "translation": "Translation",
            "original": "Original",
            "has_translation": True,
        }

        # Setup writer mock
        mock_writer = MagicMock()
        mock_writer.open.return_value = tmp_path / "bndl_20260213-1430__test__src-munzip"
        mock_writer.close.return_value = {
            "succeeded": 2,
            "failed": 0,
            "articles_path": str(tmp_path / "articles.jsonl"),
            "failed_path": str(tmp_path / "failed.jsonl"),
        }
        mock_writer_cls.return_value = mock_writer

        # Create bundle path
        bundle_path = tmp_path / "bndl_20260213-1430__test__src-munzip"
        bundle_path.mkdir()

        config = FathomConfig(db_root=str(tmp_path))
        adapter = ITKCAdapter()
        selector = parse_selector({"type": "query", "keywords": "송시열"})

        result = adapter.crawl(selector, config)

        assert result.total == 2
        assert result.succeeded == 2
        assert result.failed == 0
        assert result.bundle_path == bundle_path

    @patch('dbs.itkc.adapter.BundleWriter')
    @patch('dbs.itkc.adapter.fetch_article_content')
    def test_crawl_ids_pipeline(self, mock_fetch_content, mock_writer_cls, tmp_path):
        mock_fetch_content.return_value = {
            "title": "Article",
            "title_ko": "기사",
            "translation": "Translation",
            "original": "Original",
            "has_translation": True,
        }

        mock_writer = MagicMock()
        bundle_path = tmp_path / "bndl_20260213-1430__test__src-munzip"
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
        adapter = ITKCAdapter()
        selector = parse_selector({"type": "ids", "id_list": ["ITKC_MO_001", "ITKC_MO_002"]})

        result = adapter.crawl(selector, config)

        assert result.total == 2
        assert result.succeeded == 2

    @patch('dbs.itkc.adapter.BundleWriter')
    @patch('dbs.itkc.adapter.fetch_article_content')
    @patch('dbs.itkc.adapter.fetch_article_list_search')
    def test_crawl_with_limit(self, mock_search, mock_fetch_content, mock_writer_cls, tmp_path):
        mock_search.return_value = [
            {"자료ID": f"ITKC_MO_{i:03d}", "기사명": f"Title {i}", "서명": "書", "저자": "作者"}
            for i in range(10)
        ]

        mock_fetch_content.return_value = {
            "title": "Article",
            "title_ko": "기사",
            "translation": "Translation",
            "original": "Original",
            "has_translation": True,
        }

        mock_writer = MagicMock()
        bundle_path = tmp_path / "bndl_20260213-1430__test__src-munzip"
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
        adapter = ITKCAdapter()
        selector = parse_selector({"type": "query", "keywords": "송시열"})

        result = adapter.crawl(selector, config, limit=3)

        assert result.total == 3

    @patch('dbs.itkc.adapter.BundleWriter')
    @patch('dbs.itkc.adapter.fetch_article_content')
    @patch('dbs.itkc.adapter.fetch_article_list_search')
    def test_crawl_handles_failures(self, mock_search, mock_fetch_content, mock_writer_cls, tmp_path):
        mock_search.return_value = [
            {"자료ID": "ITKC_MO_001", "기사명": "Title 1", "서명": "書1", "저자": "作者1"},
            {"자료ID": "ITKC_MO_002", "기사명": "Title 2", "서명": "書2", "저자": "作者2"},
        ]

        # First succeeds, second fails
        mock_fetch_content.side_effect = [
            {"title": "Article", "title_ko": "기사", "translation": "Translation", "original": "Original", "has_translation": True},
            {"title": "Failed", "original": "[크롤링 실패]", "error": "Connection timeout"},
        ]

        mock_writer = MagicMock()
        bundle_path = tmp_path / "bndl_20260213-1430__test__src-munzip"
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
        adapter = ITKCAdapter()
        selector = parse_selector({"type": "query", "keywords": "송시열"})

        result = adapter.crawl(selector, config)

        assert result.succeeded == 1
        assert result.failed == 1

    @patch('dbs.itkc.adapter.BundleWriter')
    @patch('dbs.itkc.adapter.fetch_article_list_search')
    def test_crawl_empty_entries(self, mock_search, mock_writer_cls, tmp_path):
        mock_search.return_value = []

        mock_writer = MagicMock()
        bundle_path = tmp_path / "bndl_20260213-1430__test__src-munzip"
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
        adapter = ITKCAdapter()
        selector = parse_selector({"type": "query", "keywords": "nonexistent_keyword_xyz"})

        result = adapter.crawl(selector, config)

        assert result.total == 0
        assert result.succeeded == 0
        assert result.failed == 0


# ===== ITKC-specific tests =====

class TestITKCSpecific:
    def test_url_construction(self):
        content = {"title": "", "title_ko": None, "translation": "", "original": "", "has_translation": False}
        api_article = {
            "자료ID": "ITKC_MO_0367A_0010_010_0010",
            "기사명": "",
            "서명": "",
            "저자": "",
        }

        article = _convert_to_v31(content, api_article)

        assert "itemId=MO" in article["url"]
        assert "dataId=ITKC_MO_0367A_0010_010_0010" in article["url"]

    def test_resolve_ids_minimal(self):
        adapter = ITKCAdapter()
        selector = parse_selector({"type": "ids", "id_list": ["ITKC_MO_001", "ITKC_MO_002"]})

        api_articles = adapter._resolve_ids(selector)

        assert len(api_articles) == 2
        assert api_articles[0] == {"자료ID": "ITKC_MO_001"}
        assert api_articles[1] == {"자료ID": "ITKC_MO_002"}

    def test_author_parsing(self):
        content = {"title": "", "title_ko": None, "translation": "", "original": "", "has_translation": False}
        api_article = {
            "자료ID": "ITKC_MO_0367A_0001",
            "기사명": "기사",
            "서명": "栗谷全書",
            "저자": "이이(李珥, 1536~1584)",
            "저자생년": "1536",
            "저자몰년": "1584",
        }

        article = _convert_to_v31(content, api_article)

        assert article["metadata"]["author"]["birth_year"] == 1536
        assert article["metadata"]["author"]["death_year"] == 1584

    @patch('dbs.itkc.adapter.parse_author')
    def test_author_parsing_with_mock(self, mock_parse_author):
        mock_parse_author.return_value = {
            "name": "이이",
            "name_hanja": "李珥",
            "birth_year": None,
            "death_year": None,
        }

        content = {"title": "", "title_ko": None, "translation": "", "original": "", "has_translation": False}
        api_article = {
            "자료ID": "ITKC_MO_001",
            "기사명": "",
            "서명": "",
            "저자": "이이(李珥, 1536~1584)",
            "저자생년": "1536",
            "저자몰년": "1584",
        }

        article = _convert_to_v31(content, api_article)

        # birth_year and death_year are added after parse_author
        assert article["metadata"]["author"]["birth_year"] == 1536
        assert article["metadata"]["author"]["death_year"] == 1584
        mock_parse_author.assert_called_once_with("이이(李珥, 1536~1584)")

    def test_format_report(self, tmp_path):
        adapter = ITKCAdapter()
        result = CrawlResult(
            bundle_path=tmp_path / "bndl_test",
            total=500,
            succeeded=498,
            failed=2,
            articles_path=tmp_path / "articles.jsonl",
            failed_path=tmp_path / "failed.jsonl",
        )

        report = adapter.format_report(result)

        assert "문집 크롤링 완료" in report
        assert "500건" in report
        assert "498건" in report
        assert "2건" in report

    @patch('dbs.itkc.adapter.parse_seo_myeong')
    def test_seo_myeong_parsing(self, mock_parse_seo):
        mock_parse_seo.return_value = {
            "name": "율곡전서",
            "name_hanja": "栗谷全書",
        }

        content = {"title": "", "title_ko": None, "translation": "", "original": "", "has_translation": False}
        api_article = {
            "자료ID": "ITKC_MO_001",
            "기사명": "",
            "서명": "栗谷全書",
            "저자": "",
        }

        article = _convert_to_v31(content, api_article)

        assert article["metadata"]["seo_myeong"] == "율곡전서"
        assert article["metadata"]["seo_myeong_hanja"] == "栗谷全書"
        mock_parse_seo.assert_called_once_with("栗谷全書")
