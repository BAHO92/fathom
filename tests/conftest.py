"""Test configuration — register stub modules before adapter imports."""
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

FATHOM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(FATHOM_ROOT))


# ─────────────────────────────────────────────────────────────────────
# Stub modules for external script dependencies
#
# Adapters use  `from sillok_crawler import ...`  etc.  At test time
# those scripts are NOT on sys.path, so we install lightweight stubs
# that return *real* Python types (not MagicMock chains) for any
# function the adapters call at import- or convert-time.
# ─────────────────────────────────────────────────────────────────────

def _make_module(name: str, attrs: dict) -> types.ModuleType:
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


# ── sillok_crawler ──────────────────────────────────────────────────

_sillok_common_mod = _make_module("sillok.common", {})
_sillok_init_mod = _make_module("sillok", {"common": _sillok_common_mod})

def _stub_create_session_sillok():
    return MagicMock()

def _stub_fetch_article(session, url):
    return {
        "title": "", "translation": "", "original": "",
        "footnotes": {}, "category": [], "date_info": {}, "page_info": "",
    }

def _stub_parse_date_info(date_str=""):
    return {"reign": "", "year": 0, "month": 0, "day": 0, "ganzhi": "", "article_num": 1}

def _stub_parse_input_file(path):
    return []

def _stub_parse_volume_info(volume_str=""):
    return {"sillok": "", "volume": 0}

def _stub_extract_footnotes(*args, **kwargs):
    return {}

sillok_crawler_mod = _make_module("sillok_crawler", {
    "create_session": _stub_create_session_sillok,
    "fetch_article": _stub_fetch_article,
    "parse_date_info": _stub_parse_date_info,
    "parse_input_file": _stub_parse_input_file,
    "parse_volume_info": _stub_parse_volume_info,
    "extract_footnotes": _stub_extract_footnotes,
})


# ── sillok_search ──────────────────────────────────────────────────

class StubSillokSearcher:
    def __init__(self, tab="w"):
        self.tab = tab
    def setup_session(self): pass
    def close(self): pass
    def count_only(self, keywords): return 0
    def search_multiple_keywords(self, keywords): return {"entries": []}

def _stub_filter_by_reign_range(entries, from_, to_):
    return entries

sillok_search_mod = _make_module("sillok_search", {
    "SillokSearcher": StubSillokSearcher,
    "REIGN_ORDER": [],
    "filter_by_reign_range": _stub_filter_by_reign_range,
})


# ── sjw_crawler ──────────────────────────────────────────────────

def _stub_create_session_sjw():
    return MagicMock()

def _stub_fetch_article_sjw(session, article_id):
    return {
        "title": "", "translation": "", "original": "",
        "has_translation": False, "itkc_data_id": "", "source_info": {},
    }

def _stub_parse_article_id(article_id):
    return {"reign": "", "year": 0, "month": 0, "day": 0, "ganzhi": "", "article_num": 1}

def _stub_parse_source_info(*args, **kwargs):
    return {}

def _stub_browse_collect_entries(reign, year_from=None, year_to=None):
    return []

sjw_crawler_mod = _make_module("sjw_crawler", {
    "create_session": _stub_create_session_sjw,
    "fetch_article": _stub_fetch_article_sjw,
    "parse_article_id": _stub_parse_article_id,
    "parse_source_info": _stub_parse_source_info,
    "browse_collect_entries": _stub_browse_collect_entries,
    "KING_CODES": {},
    "KING_NAMES_TO_CODES": {},
    "SJW_BASE": "https://sjw.history.go.kr",
})


# ── sjw_search ──────────────────────────────────────────────────

class StubSjwSearcher:
    def __init__(self): pass
    def setup_session(self): pass
    def close(self): pass
    def search(self, keywords, field="all", king_name="ALL"): return (0, [], None)
    def search_and_collect(self, keyword, field="all", king_name="ALL", limit=None): return {"entries": []}

def _stub_sjw_filter_by_reign_range(entries, from_, to_):
    return entries

sjw_search_mod = _make_module("sjw_search", {
    "SjwSearcher": StubSjwSearcher,
    "filter_by_reign_range": _stub_sjw_filter_by_reign_range,
})


# ── munzip_crawler ──────────────────────────────────────────────

def _stub_fetch_api(params):
    return {"total_count": 0, "docs": []}

def _stub_fetch_article_list_search(collection_id=None, query="", sec_id="MO_BD", limit=None):
    return []

def _stub_fetch_article_list_full(collection_id="", limit=None):
    return []

def _stub_fetch_article_content(data_id):
    return {"title": "", "title_ko": None, "translation": "", "original": "", "has_translation": False}

def _stub_parse_author(author_str):
    return {"name": "", "name_hanja": "", "birth_year": None, "death_year": None}

def _stub_parse_seo_myeong(seo_str):
    return {"name": seo_str, "name_hanja": seo_str}

def _stub_get_sec_id_for_collection(collection_id, suffix):
    return f"{collection_id}_{suffix}"

def _stub_clean_text(text):
    return text

munzip_crawler_mod = _make_module("munzip_crawler", {
    "fetch_api": _stub_fetch_api,
    "fetch_article_list_search": _stub_fetch_article_list_search,
    "fetch_article_list_full": _stub_fetch_article_list_full,
    "fetch_article_content": _stub_fetch_article_content,
    "parse_author": _stub_parse_author,
    "parse_seo_myeong": _stub_parse_seo_myeong,
    "get_sec_id_for_collection": _stub_get_sec_id_for_collection,
    "clean_text": _stub_clean_text,
    "WEB_BASE": "https://db.itkc.or.kr",
})


# ── Register all stubs (MUST happen before any adapter import) ──

sys.modules["sillok"] = _sillok_init_mod
sys.modules["sillok.common"] = _sillok_common_mod
sys.modules["sillok_crawler"] = sillok_crawler_mod
sys.modules["sillok_search"] = sillok_search_mod
sys.modules["sjw_crawler"] = sjw_crawler_mod
sys.modules["sjw_search"] = sjw_search_mod
sys.modules["munzip_crawler"] = munzip_crawler_mod


# ─────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────

@pytest.fixture
def fathom_root():
    return FATHOM_ROOT


@pytest.fixture
def tmp_config_dir(tmp_path):
    return tmp_path
