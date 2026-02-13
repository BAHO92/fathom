import json
import os
import re
from pathlib import Path

import pytest
import yaml

from engine.selector import Selector, parse_selector, validate_selector, SELECTOR_TYPES
from engine.config import FathomConfig, load_config, save_config, is_first_run, get_fathom_root
from engine.output import (
    BundleWriter, make_bundle_path, make_slug,
    format_article, format_failed, write_jsonl, append_jsonl,
)
from engine.provenance import ProvenanceBuilder, write_provenance, compute_file_sha256
from engine.onboarding import (
    check_onboarding, get_welcome_message, get_db_root_prompt,
    get_db_selection_prompt, get_appendix_prompt, get_completion_message,
    parse_db_selection, parse_appendix_selection, create_config_from_onboarding,
    APPENDIX_CATALOG, DB_DISPLAY_NAMES,
)
from engine.workflow import parse_intent, format_confirmation, check_onboarding as wf_check_onboarding


# ===== Selector =====

class TestSelector:
    def test_query_selector(self):
        s = parse_selector({"type": "query", "keywords": "宋時烈"})
        assert s.type == "query"
        assert s.keywords == "宋時烈"

    def test_query_with_layer(self):
        s = parse_selector({"type": "query", "keywords": "송시열", "layer": "translation"})
        assert s.layer == "translation"

    def test_time_range_selector(self):
        s = parse_selector({"type": "time_range", "reign": "현종", "year_from": 1, "year_to": 5})
        assert s.type == "time_range"
        assert s.reign == "현종"
        assert s.year_from == 1
        assert s.year_to == 5

    def test_work_scope_selector(self):
        s = parse_selector({"type": "work_scope", "work_kind": "collection", "work_id": "ITKC_MO_0367A"})
        assert s.type == "work_scope"
        assert s.work_kind == "collection"

    def test_ids_with_list(self):
        s = parse_selector({"type": "ids", "id_list": ["a", "b", "c"]})
        assert s.type == "ids"
        assert len(s.id_list) == 3

    def test_ids_with_file(self):
        s = parse_selector({"type": "ids", "source_file": "/tmp/ids.txt"})
        assert s.source_file == "/tmp/ids.txt"

    def test_invalid_type_raises(self):
        with pytest.raises(ValueError, match="Invalid selector type"):
            parse_selector({"type": "invalid"})

    def test_missing_keywords_raises(self):
        with pytest.raises(ValueError, match="keywords"):
            parse_selector({"type": "query"})

    def test_missing_reign_raises(self):
        with pytest.raises(ValueError, match="reign"):
            parse_selector({"type": "time_range"})

    def test_missing_work_fields_raises(self):
        with pytest.raises(ValueError):
            parse_selector({"type": "work_scope"})

    def test_missing_ids_raises(self):
        with pytest.raises(ValueError):
            parse_selector({"type": "ids"})

    def test_non_dict_raises(self):
        with pytest.raises(ValueError, match="Expected dict"):
            parse_selector("not a dict")

    def test_validate_unsupported_selector(self):
        s = parse_selector({"type": "query", "keywords": "test"})
        errors = validate_selector(s, {"selectors": ["work_scope"]})
        assert any("not supported" in e for e in errors)

    def test_validate_supported_selector(self):
        s = parse_selector({"type": "query", "keywords": "test"})
        errors = validate_selector(s, {"selectors": ["query", "work_scope"]})
        assert len(errors) == 0

    def test_all_selector_types(self):
        assert set(SELECTOR_TYPES) == {"query", "time_range", "work_scope", "ids"}

    def test_options_passthrough(self):
        s = parse_selector({"type": "query", "keywords": "test", "options": {"tab": "w"}})
        assert s.options == {"tab": "w"}


# ===== Config =====

class TestConfig:
    def test_defaults(self):
        cfg = FathomConfig()
        assert cfg.db_root == "~/DB"
        assert cfg.enabled_dbs == ["sillok", "sjw", "itkc"]
        assert cfg.language == "ko"
        assert cfg.extended_provenance is False

    def test_resolved_db_root(self):
        cfg = FathomConfig(db_root="~/DB")
        resolved = cfg.resolved_db_root()
        assert resolved.is_absolute()
        assert "~" not in str(resolved)

    def test_load_defaults_only(self, tmp_config_dir):
        cfg = load_config(tmp_config_dir)
        assert cfg.db_root == "~/DB"

    def test_load_default_json(self, tmp_config_dir):
        default = {"db_root": "/custom/path", "language": "en"}
        (tmp_config_dir / "config.default.json").write_text(json.dumps(default))
        cfg = load_config(tmp_config_dir)
        assert cfg.db_root == "/custom/path"
        assert cfg.language == "en"

    def test_user_config_overrides_default(self, tmp_config_dir):
        default = {"db_root": "/default"}
        user = {"db_root": "/user"}
        (tmp_config_dir / "config.default.json").write_text(json.dumps(default))
        (tmp_config_dir / "config.json").write_text(json.dumps(user))
        cfg = load_config(tmp_config_dir)
        assert cfg.db_root == "/user"

    def test_save_and_reload(self, tmp_config_dir):
        cfg = FathomConfig(db_root="/test/db", enabled_dbs=["sillok"])
        path = save_config(cfg, tmp_config_dir)
        assert path.exists()
        reloaded = load_config(tmp_config_dir)
        assert reloaded.db_root == "/test/db"
        assert reloaded.enabled_dbs == ["sillok"]

    def test_is_first_run(self, tmp_config_dir):
        assert is_first_run(tmp_config_dir) is True
        save_config(FathomConfig(), tmp_config_dir)
        assert is_first_run(tmp_config_dir) is False

    def test_get_fathom_root(self):
        root = get_fathom_root()
        assert (root / "engine" / "config.py").exists()

    def test_ignores_unknown_keys(self, tmp_config_dir):
        data = {"db_root": "/x", "unknown_key": "should_be_ignored"}
        (tmp_config_dir / "config.json").write_text(json.dumps(data))
        cfg = load_config(tmp_config_dir)
        assert cfg.db_root == "/x"
        assert not hasattr(cfg, "unknown_key")

    def test_corrupt_json_fallback(self, tmp_config_dir):
        (tmp_config_dir / "config.json").write_text("{bad json")
        cfg = load_config(tmp_config_dir)
        assert cfg.db_root == "~/DB"


# ===== Output =====

class TestOutput:
    def test_make_slug_ascii(self):
        assert make_slug("Hello World") == "hello-world"

    def test_make_slug_korean(self):
        assert make_slug("송시열") == "unnamed"

    def test_make_slug_mixed(self):
        slug = make_slug("Song 시열 test")
        assert "song" in slug
        assert "test" in slug

    def test_make_slug_empty(self):
        assert make_slug("") == "unnamed"

    def test_make_slug_max_length(self):
        long_text = "a" * 100
        assert len(make_slug(long_text)) <= 50

    def test_bundle_path_format(self):
        path = make_bundle_path("/tmp/db", "sillok", "song-siyeol")
        name = path.name
        assert name.startswith("bndl_")
        assert "__song-siyeol__" in name
        assert "__src-sillok" in name

    def test_bundle_path_multi_source_order(self):
        path = make_bundle_path("/tmp/db", "sjw", "test", sources=["sjw", "sillok", "itkc"])
        name = path.name
        assert "src-sillok-sjw-itkc" in name

    def test_format_article_adds_metadata(self):
        raw = {"id": "test_001", "title": "Test"}
        article = format_article(raw, "sillok")
        assert article["schema_version"] == "3.1"
        assert article["source"] == "sillok"
        assert "crawled_at" in article

    def test_format_article_preserves_existing(self):
        raw = {"id": "x", "schema_version": "2.0", "source": "custom"}
        article = format_article(raw, "sillok")
        assert article["schema_version"] == "2.0"
        assert article["source"] == "custom"

    def test_format_failed(self):
        f = format_failed("id_1", "http://x", "timeout", retries=3)
        assert f["id"] == "id_1"
        assert f["error"] == "timeout"
        assert f["retries"] == 3
        assert "timestamp" in f

    def test_write_jsonl(self, tmp_path):
        records = [{"a": 1}, {"b": 2}]
        path = tmp_path / "out.jsonl"
        count = write_jsonl(path, records)
        assert count == 2
        lines = path.read_text().strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0]) == {"a": 1}

    def test_append_jsonl(self, tmp_path):
        path = tmp_path / "out.jsonl"
        append_jsonl(path, {"a": 1})
        append_jsonl(path, {"b": 2})
        lines = path.read_text().strip().split("\n")
        assert len(lines) == 2

    def test_bundle_writer_lifecycle(self, tmp_path):
        writer = BundleWriter(str(tmp_path), "sillok", "test-bundle")
        bundle_path = writer.open()
        assert bundle_path.exists()
        writer.write_article({"id": "1", "data": "ok"})
        writer.write_article({"id": "2", "data": "ok"})
        writer.write_failed({"id": "3", "error": "fail"})
        result = writer.close()
        assert result["succeeded"] == 2
        assert result["failed"] == 1
        articles = Path(result["articles_path"]).read_text().strip().split("\n")
        assert len(articles) == 2

    def test_bundle_writer_not_opened_raises(self):
        writer = BundleWriter("/tmp", "sillok", "test")
        with pytest.raises(RuntimeError, match="not opened"):
            writer.write_article({"x": 1})


# ===== Provenance =====

class TestProvenance:
    def test_core_provenance(self):
        pb = ProvenanceBuilder("20260213-1430--abc123", "bndl_test", extended=False)
        pb.set_tool_info("fathom", "1.0.0")
        pb.add_task("t1", "sillok", "search", {"keyword": "송시열"}, {"keywords": ["송시열"]})
        pb.update_task_stats("t1", selected=100, succeeded=98, failed=2)
        pb.set_outputs("articles.jsonl", 98, "failed.jsonl", 2)
        prov = pb.build()

        assert prov["schema_version"] == "fathom.bundle_provenance.v1"
        assert prov["bundle"]["bundle_id"] == "20260213-1430--abc123"
        assert prov["tool"]["name"] == "fathom"
        assert len(prov["tasks"]) == 1
        assert prov["tasks"][0]["stats"]["succeeded"] == 98
        assert prov["outputs"]["files"]["articles"]["records"] == 98
        assert "integrity" not in prov

    def test_extended_provenance(self):
        pb = ProvenanceBuilder("id", "folder", extended=True)
        pb.set_tool_info("fathom", "1.0.0")
        pb.set_cli_argv(["fathom", "crawl", "--db", "sillok"])
        pb.add_task("t1", "sillok", "search", {}, {})
        pb.update_task_stats("t1", selected=10, succeeded=10, failed=0, duration_ms=5000)
        pb.set_outputs("articles.jsonl", 10)
        pb.set_resume_info("fresh")
        pb.set_notes("test run")
        prov = pb.build()

        assert "git" in prov["tool"] or "runtime" in prov["tool"]
        assert prov["reproduce"]["cli"]["argv"] == ["fathom", "crawl", "--db", "sillok"]
        assert "integrity" in prov
        assert prov["resume"]["kind"] == "fresh"
        assert prov["notes"] == "test run"

    def test_update_unknown_task_raises(self):
        pb = ProvenanceBuilder("id", "folder")
        with pytest.raises(ValueError, match="not found"):
            pb.update_task_stats("nonexistent")

    def test_write_provenance_file(self, tmp_path):
        prov = {"schema_version": "test", "data": "ok"}
        path = tmp_path / "provenance.json"
        write_provenance(path, prov)
        loaded = json.loads(path.read_text())
        assert loaded["schema_version"] == "test"

    def test_compute_sha256(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world")
        h = compute_file_sha256(f)
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)


# ===== Onboarding =====

class TestOnboarding:
    def test_check_first_run(self, tmp_config_dir):
        assert check_onboarding(tmp_config_dir) is True

    def test_check_after_config_created(self, tmp_config_dir):
        save_config(FathomConfig(), tmp_config_dir)
        assert check_onboarding(tmp_config_dir) is False

    def test_welcome_message_polite(self):
        msg = get_welcome_message()
        assert "처음 사용하시는군요" in msg
        assert "진행하겠습니다" in msg

    def test_db_root_prompt(self):
        msg = get_db_root_prompt("~/CustomDB")
        assert "~/CustomDB" in msg

    def test_db_selection_prompt_lists_all(self):
        msg = get_db_selection_prompt()
        for db_id in DB_DISPLAY_NAMES:
            assert db_id in msg

    def test_appendix_prompt_lists_fields(self):
        msg = get_appendix_prompt(["sillok", "sjw"])
        assert "day_articles" in msg
        assert "person_annotations" in msg
        assert "1." in msg
        assert "번호" in msg

    def test_completion_message(self):
        cfg = FathomConfig(enabled_dbs=["sillok"], appendix_fields={"sillok": ["day_articles"]})
        msg = get_completion_message(cfg)
        assert "완료되었습니다" in msg
        assert "조선왕조실록" in msg
        assert "day_articles" in msg

    def test_parse_db_selection_empty(self):
        assert parse_db_selection("") == ["sillok", "sjw", "itkc"]

    def test_parse_db_selection_specific(self):
        assert parse_db_selection("sillok, sjw") == ["sillok", "sjw"]

    def test_parse_db_selection_invalid_fallback(self):
        assert parse_db_selection("invalid_db") == ["sillok", "sjw", "itkc"]

    def test_parse_appendix_empty(self):
        result = parse_appendix_selection("", ["sillok"])
        assert result == {"sillok": []}

    def test_parse_appendix_single_db(self):
        result = parse_appendix_selection("sillok: day_articles, prev_article_id", ["sillok", "sjw"])
        assert result["sillok"] == ["day_articles", "prev_article_id"]
        assert result["sjw"] == []

    def test_parse_appendix_multi_db(self):
        result = parse_appendix_selection(
            "sillok: day_articles; sjw: person_annotations",
            ["sillok", "sjw", "itkc"],
        )
        assert result["sillok"] == ["day_articles"]
        assert result["sjw"] == ["person_annotations"]
        assert result["itkc"] == []

    def test_parse_appendix_ignores_invalid_fields(self):
        result = parse_appendix_selection("sillok: fake_field", ["sillok"])
        assert result["sillok"] == []

    def test_create_config(self, tmp_config_dir):
        cfg = create_config_from_onboarding(
            db_root="/test",
            enabled_dbs=["sillok"],
            appendix_fields={"sillok": ["day_articles"]},
            base_dir=tmp_config_dir,
        )
        assert cfg.db_root == "/test"
        assert cfg.enabled_dbs == ["sillok"]
        assert (tmp_config_dir / "config.json").exists()

    def test_no_banmal_in_messages(self):
        banmal_patterns = ["해줘", "할까", "할게", "있어$", "없어$", "됐어"]
        messages = [
            get_welcome_message(),
            get_db_root_prompt(),
            get_db_selection_prompt(),
            get_appendix_prompt(["sillok", "sjw", "itkc"]),
        ]
        for msg in messages:
            for pattern in banmal_patterns:
                assert not re.search(pattern, msg), f"반말 detected: '{pattern}' in message"


# ===== Workflow =====

class TestWorkflow:
    def test_parse_intent_sillok_query(self):
        intent = parse_intent("실록에서 '송시열' 검색")
        assert intent["db"] == "sillok"
        assert intent["selector_type"] == "query"
        assert intent["params"].get("keywords") == "송시열"

    def test_parse_intent_sjw_time(self):
        intent = parse_intent("승정원일기 인조 시기 전체")
        assert intent["db"] == "sjw"
        assert intent["selector_type"] == "time_range"

    def test_parse_intent_itkc_work_scope(self):
        intent = parse_intent("문집 ITKC_MO_0367A 전체 수집")
        assert intent["db"] == "itkc"
        assert intent["selector_type"] == "work_scope"
        assert intent["params"].get("work_id") == "ITKC_MO_0367A"

    def test_parse_intent_unknown_db(self):
        intent = parse_intent("뭔가 해줘")
        assert intent["db"] is None
        assert intent["confidence"] == "low"
        assert len(intent["ambiguities"]) > 0

    def test_format_confirmation_exact(self):
        from dbs.base import CountResult
        msg = format_confirmation("조선왕조실록", "'송시열' 검색 (원문)", CountResult(kind="exact", count=412))
        assert "412" in msg
        assert "진행하시겠습니까" in msg

    def test_format_confirmation_estimate(self):
        from dbs.base import CountResult
        msg = format_confirmation("승정원일기", "현종 전체", CountResult(kind="estimate", count=5000))
        assert "추정" in msg

    def test_format_confirmation_unknown(self):
        from dbs.base import CountResult
        msg = format_confirmation("승정원일기", "인조 시기", CountResult(kind="unknown"))
        assert "수집 시작 후" in msg

    def test_load_adapter_sillok(self):
        from engine.workflow import load_adapter
        a = load_adapter("sillok")
        assert a.db_id == "sillok"

    def test_load_adapter_sjw(self):
        from engine.workflow import load_adapter
        a = load_adapter("sjw")
        assert a.db_id == "sjw"

    def test_load_adapter_itkc(self):
        from engine.workflow import load_adapter
        a = load_adapter("itkc")
        assert a.db_id == "itkc"

    def test_load_adapter_invalid(self):
        from engine.workflow import load_adapter
        with pytest.raises(ValueError, match="Invalid db_id"):
            load_adapter("nonexistent")

    def test_check_onboarding_delegates(self, tmp_config_dir):
        assert wf_check_onboarding() == is_first_run()


# ===== Registry =====

class TestRegistry:
    def test_registry_loads(self, fathom_root):
        path = fathom_root / "registry.yaml"
        assert path.exists()
        with open(path) as f:
            reg = yaml.safe_load(f)
        assert "databases" in reg
        assert set(reg["databases"].keys()) == {"sillok", "sjw", "itkc"}

    def test_registry_selectors(self, fathom_root):
        with open(fathom_root / "registry.yaml") as f:
            reg = yaml.safe_load(f)
        for db_id, db in reg["databases"].items():
            assert "selectors" in db
            for sel in db["selectors"]:
                assert sel in SELECTOR_TYPES, f"{db_id} has unknown selector: {sel}"

    def test_registry_scripts_exist(self, fathom_root):
        with open(fathom_root / "registry.yaml") as f:
            reg = yaml.safe_load(f)
        for db_id, db in reg["databases"].items():
            for script_key, script_path in db.get("scripts", {}).items():
                full_path = fathom_root / script_path
                assert full_path.exists(), f"{db_id}.scripts.{script_key}: {script_path} not found"
