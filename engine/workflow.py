"""3-stage workflow engine for fathom.

Orchestrates the collection workflow:
  1. parse_intent: Natural language → structured intent
  2. preflight: Count articles and confirm with user
  3. execute: Run crawl and generate report
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Any

from engine.config import load_config, is_first_run, FathomConfig
from engine.selector import Selector, parse_selector, validate_selector
from dbs.base import BaseAdapter, CountResult, CrawlResult


# === Stage 1: Intent Parsing ===

def parse_intent(user_input: str) -> dict:
    """Parse natural language into structured intent.
    
    Args:
        user_input: User's natural language request.
    
    Returns:
        Dict with:
            db: "sillok" | "sjw" | "itkc" | None
            selector_type: "query" | "time_range" | "work_scope" | "ids" | None
            params: Dict of extracted parameters
            confidence: "high" | "medium" | "low"
            ambiguities: List of ambiguous aspects
    """
    input_lower = user_input.lower()
    
    db_id = None
    db_keywords = {
        "sillok": ["실록", "sillok", "조선왕조실록"],
        "sjw": ["승정원", "sjw", "승정원일기"],
        "itkc": ["문집", "itkc", "한국고전", "고전종합"],
    }
    
    for db, keywords in db_keywords.items():
        if any(kw in input_lower for kw in keywords):
            db_id = db
            break
    
    selector_type = None
    params = {}
    
    reign_pattern = r"(세종|세조|성종|중종|선조|인조|현종|숙종|영조|정조)"
    reign_match = re.search(reign_pattern, user_input)
    
    if any(kw in input_lower for kw in ["검색", "키워드", "찾아"]):
        selector_type = "query"
        for pattern in [r"['\"]([^'\"]+)['\"]", r"검색[:\s]*(\S+)", r"키워드[:\s]*(\S+)"]:
            match = re.search(pattern, user_input)
            if match:
                params["keywords"] = match.group(1)
                break
    
    elif reign_match or any(kw in input_lower for kw in ["년대", "시기", "날짜", "범위"]):
        selector_type = "time_range"
        if reign_match:
            params["reign"] = reign_match.group(1)
        year_match = re.search(r"(\d{4})[년]*", user_input)
        if year_match:
            params["year_from"] = int(year_match.group(1))
    
    elif any(kw in input_lower for kw in ["전체", "서지", "문집명"]):
        selector_type = "work_scope"
        itkc_match = re.search(r"(ITKC_[A-Z]{2}_\d{4}[A-Z])", user_input, re.IGNORECASE)
        if itkc_match:
            params["work_id"] = itkc_match.group(1).upper()
            params["work_kind"] = "collection"
    
    elif any(kw in input_lower for kw in ["id", "목록", "리스트"]):
        selector_type = "ids"
        file_match = re.search(r"파일[:\s]*(\S+)", user_input)
        if file_match:
            params["source_file"] = file_match.group(1)
    
    confidence = "high"
    ambiguities = []
    
    if db_id is None:
        ambiguities.append("대상 DB를 확인할 수 없습니다.")
        confidence = "low"
    
    if selector_type is None:
        ambiguities.append("수집 방식(검색/날짜/전체/ID)을 확인할 수 없습니다.")
        confidence = "low"
    elif not params:
        ambiguities.append("수집 파라미터가 명확하지 않습니다.")
        confidence = "medium"
    
    return {
        "db": db_id,
        "selector_type": selector_type,
        "params": params,
        "confidence": confidence,
        "ambiguities": ambiguities,
    }


# === Stage 2: Preflight ===

def preflight(adapter: BaseAdapter, selector: Selector) -> dict:
    """Run preflight check and return summary.
    
    Args:
        adapter: DB adapter instance.
        selector: Parsed selector.
    
    Returns:
        Dict with:
            count: CountResult
            selector_summary: Human-readable selector description
            warnings: List of warning messages
            confirmation_message: Polite confirmation message
    """
    capabilities = adapter.capabilities()
    validation_errors = validate_selector(selector, capabilities)
    
    if validation_errors:
        return {
            "count": CountResult(kind="unknown"),
            "selector_summary": "",
            "warnings": validation_errors,
            "confirmation_message": "",
        }
    
    count_result = adapter.count(selector)
    selector_summary = _format_selector_summary(selector, adapter.db_id)
    db_name = _get_db_name(adapter.db_id)
    confirmation_message = format_confirmation(db_name, selector_summary, count_result)
    
    warnings = []
    if count_result.kind == "estimate":
        warnings.append("정확한 건수는 수집 시작 후 확인됩니다.")
    if count_result.count and count_result.count > 10000:
        warnings.append("대량 수집입니다. 완료까지 시간이 오래 걸릴 수 있습니다.")
    
    return {
        "count": count_result,
        "selector_summary": selector_summary,
        "warnings": warnings,
        "confirmation_message": confirmation_message,
    }


def format_confirmation(db_name: str, selector_summary: str, count: CountResult) -> str:
    """Generate polite Korean confirmation message.
    
    Args:
        db_name: Database display name.
        selector_summary: Human-readable selector description.
        count: CountResult from adapter.
    
    Returns:
        Formatted confirmation message in polite Korean.
    """
    if count.kind == "exact":
        return (
            f"{db_name}에서 {selector_summary} 결과, "
            f"약 {count.count:,}건이 확인되었습니다.\n"
            f"수집을 진행하시겠습니까?"
        )
    elif count.kind == "estimate":
        return (
            f"{db_name}에서 {selector_summary} 결과, "
            f"약 {count.count:,}건(추정)이 확인되었습니다.\n"
            f"수집을 진행하시겠습니까?"
        )
    else:
        return (
            f"{db_name}에서 {selector_summary} 수집을 진행하시겠습니까?\n"
            f"(건수는 수집 시작 후 확인됩니다.)"
        )


def _format_selector_summary(selector: Selector, db_id: str) -> str:
    """Format selector as human-readable description."""
    if selector.type == "query":
        layer_text = ""
        if selector.layer == "original":
            layer_text = " (원문)"
        elif selector.layer == "translation":
            layer_text = " (국역)"
        return f"'{selector.keywords}' 검색{layer_text}"
    
    elif selector.type == "time_range":
        if selector.reign and selector.year_from and selector.year_to:
            return f"{selector.reign} {selector.year_from}년 ~ {selector.year_to}년"
        elif selector.reign:
            return f"{selector.reign} 전체"
        elif selector.year_from and selector.year_to:
            return f"{selector.year_from}년 ~ {selector.year_to}년"
        else:
            return "날짜 범위"
    
    elif selector.type == "work_scope":
        if selector.work_id:
            return f"{selector.work_id} 전체"
        else:
            return "문집 전체"
    
    elif selector.type == "ids":
        if selector.source_file:
            return f"ID 목록 ({selector.source_file})"
        elif selector.id_list:
            return f"ID 목록 ({len(selector.id_list)}건)"
        else:
            return "ID 기반 수집"
    
    return selector.type


def _get_db_name(db_id: str) -> str:
    """Get display name for DB ID."""
    names = {
        "sillok": "조선왕조실록",
        "sjw": "승정원일기",
        "itkc": "한국고전종합DB (문집)",
    }
    return names.get(db_id, db_id)


# === Stage 3: Execute + Report ===

def execute(
    adapter: BaseAdapter,
    selector: Selector,
    config: FathomConfig,
    limit: Optional[int] = None
) -> dict:
    """Execute crawl and return report.
    
    Args:
        adapter: DB adapter instance.
        selector: Parsed selector.
        config: Fathom configuration.
        limit: Optional limit on number of articles.
    
    Returns:
        Dict with:
            result: CrawlResult
            report: Formatted report string
            next_steps: List of suggested next steps
    """
    result = adapter.crawl(selector, config, limit=limit)
    report = adapter.format_report(result)
    next_steps = []
    
    if result.failed > 0 and result.failed_path:
        next_steps.append(
            f"실패 기사 재시도: python3 dbs/{adapter.db_id}/scripts/*_crawler.py "
            f"--ids {result.failed_path}"
        )
    
    next_steps.append(f"전처리 진행: /db-preprocessing {result.bundle_path}")
    
    return {
        "result": result,
        "report": report,
        "next_steps": next_steps,
    }


# === Adapter Loading ===

def load_adapter(db_id: str) -> BaseAdapter:
    """Load adapter by db_id from registry.
    
    Args:
        db_id: Database identifier (sillok, sjw, itkc).
    
    Returns:
        BaseAdapter instance.
    
    Raises:
        ImportError: If adapter module not found.
        ValueError: If db_id is invalid.
    """
    # Map db_id to adapter class name (not all are simple capitalize)
    _adapter_classes = {
        "sillok": "SillokAdapter",
        "sjw": "SJWAdapter",
        "itkc": "ITKCAdapter",
    }

    if db_id not in _adapter_classes:
        raise ValueError(
            f"Invalid db_id '{db_id}'. Must be one of: {', '.join(_adapter_classes)}"
        )

    class_name = _adapter_classes[db_id]
    try:
        module = __import__(f"dbs.{db_id}.adapter", fromlist=["adapter"])
        adapter_class = getattr(module, class_name)
        return adapter_class()
    except (ImportError, AttributeError) as e:
        raise ImportError(
            f"Failed to load adapter for '{db_id}'. "
            f"Ensure dbs/{db_id}/adapter.py exists and defines {class_name}."
        ) from e


# === Onboarding Detection ===

def check_onboarding() -> bool:
    """Check if first run and onboarding needed.
    
    Returns:
        True if config.json does not exist (first-time user).
    """
    return is_first_run()
