"""First-run onboarding for fathom.

Detects first-time users (no config.json) and provides guided setup
messages for Claude to present. All user-facing text uses 존댓말.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from engine.config import (
    FathomConfig,
    get_fathom_root,
    is_first_run,
    load_config,
    save_config,
)


# ── Appendix field descriptions (for onboarding menu) ──

APPENDIX_CATALOG: Dict[str, Dict[str, str]] = {
    "sillok": {
        "day_articles": "같은 날 기사 목록 (네비게이션용)",
        "prev_article_id": "이전 기사 ID",
        "next_article_id": "다음 기사 ID",
        "place_annotations": "지명 annotation (일부 기사)",
        "book_annotations": "서명 annotation (일부 기사)",
    },
    "sjw": {
        "person_annotations": "SJW 페이지 인명/관직 마크업",
        "day_total_articles": "같은 날 기사 총수",
    },
    "itkc": {
        "page_markers": "원문 페이지 구분 마커 (렌더링용)",
        "indent_levels": "원문/번역 들여쓰기 레벨 (렌더링용)",
    },
}

DB_DISPLAY_NAMES: Dict[str, str] = {
    "sillok": "조선왕조실록",
    "sjw": "승정원일기",
    "itkc": "한국고전종합DB (문집)",
}


def check_onboarding(base_dir: Optional[Path] = None) -> bool:
    """Check whether first-run onboarding is needed.

    Returns:
        True if config.json does not exist yet.
    """
    return is_first_run(base_dir)


def get_welcome_message() -> str:
    """Return the first-run welcome message (존댓말)."""
    return (
        "fathom을 처음 사용하시는군요! 간단한 설정을 진행하겠습니다.\n"
        "\n"
        "다음 세 가지를 확인해 드리겠습니다:\n"
        "  1. 수집 데이터 저장 경로\n"
        "  2. 활성화할 데이터베이스\n"
        "  3. 추가 수집 필드(appendix) 설정\n"
    )


def get_db_root_prompt(current: str = "~/DB") -> str:
    """Return the DB root path prompt message."""
    return (
        f"수집한 데이터를 저장할 경로를 지정해 주세요.\n"
        f"(기본값: {current})\n"
        f"Enter를 누르시면 기본값을 사용합니다."
    )


def get_db_selection_prompt() -> str:
    """Return the DB selection prompt with available databases."""
    lines = ["활성화할 데이터베이스를 선택해 주세요. (기본값: 전체)\n"]
    for db_id, name in DB_DISPLAY_NAMES.items():
        lines.append(f"  - {db_id}: {name}")
    lines.append("\n쉼표로 구분하여 입력해 주세요. (예: sillok, sjw)")
    lines.append("Enter를 누르시면 전체를 활성화합니다.")
    return "\n".join(lines)


def get_appendix_prompt(enabled_dbs: List[str]) -> str:
    """Return the appendix field selection prompt.

    Args:
        enabled_dbs: List of enabled DB IDs.

    Returns:
        Formatted prompt listing appendix fields per DB.
    """
    lines = [
        "추가 수집 필드(appendix)를 설정하시겠습니까?\n",
        "appendix 필드는 렌더링/네비게이션용 부수 데이터입니다.",
        "기본값은 수집하지 않으며, 필요한 항목만 선택하실 수 있습니다.\n",
    ]

    for db_id in enabled_dbs:
        catalog = APPENDIX_CATALOG.get(db_id, {})
        if not catalog:
            continue
        db_name = DB_DISPLAY_NAMES.get(db_id, db_id)
        lines.append(f"[{db_name}]")
        for field_name, desc in catalog.items():
            lines.append(f"  ◈ {field_name}: {desc}")
        lines.append("")

    lines.append("DB별로 활성화할 필드를 알려 주세요.")
    lines.append('(예: "sillok: day_articles, prev_article_id")')
    lines.append("Enter를 누르시면 appendix 없이 core 필드만 수집합니다.")
    return "\n".join(lines)


def get_completion_message(config: FathomConfig) -> str:
    """Return the onboarding completion message.

    Args:
        config: The newly saved configuration.
    """
    db_names = [
        DB_DISPLAY_NAMES.get(db, db) for db in config.enabled_dbs
    ]
    db_list = ", ".join(db_names)

    appendix_summary_parts = []
    for db_id, fields in config.appendix_fields.items():
        if fields:
            appendix_summary_parts.append(f"{db_id}: {', '.join(fields)}")

    appendix_text = (
        ", ".join(appendix_summary_parts) if appendix_summary_parts
        else "없음 (core 필드만 수집)"
    )

    return (
        "설정이 완료되었습니다!\n"
        "\n"
        f"  저장 경로: {config.db_root}\n"
        f"  활성 DB: {db_list}\n"
        f"  Appendix: {appendix_text}\n"
        "\n"
        "설정은 config.json에 저장되었습니다.\n"
        "언제든 config.json을 직접 수정하시거나, 삭제 후 다시 설정하실 수 있습니다.\n"
        "\n"
        "이제 크롤링을 시작하실 수 있습니다!"
    )


def parse_db_selection(user_input: str) -> List[str]:
    """Parse user's DB selection input.

    Args:
        user_input: Comma-separated DB IDs or empty string for all.

    Returns:
        List of valid DB IDs.
    """
    if not user_input.strip():
        return list(DB_DISPLAY_NAMES.keys())

    valid_dbs = set(DB_DISPLAY_NAMES.keys())
    selected = []
    for token in user_input.split(","):
        db_id = token.strip().lower()
        if db_id in valid_dbs:
            selected.append(db_id)

    return selected if selected else list(DB_DISPLAY_NAMES.keys())


def parse_appendix_selection(
    user_input: str,
    enabled_dbs: List[str],
) -> Dict[str, List[str]]:
    """Parse user's appendix field selection.

    Supports format: ``"sillok: field1, field2; sjw: field3"``
    or ``"sillok: field1, field2"`` (single DB).

    Args:
        user_input: User input string.
        enabled_dbs: List of enabled DB IDs.

    Returns:
        Dict mapping db_id to list of appendix field names.
    """
    result: Dict[str, List[str]] = {db: [] for db in enabled_dbs}

    if not user_input.strip():
        return result

    # Split by semicolon for multi-DB, or parse single DB
    segments = user_input.split(";") if ";" in user_input else [user_input]

    for segment in segments:
        segment = segment.strip()
        if ":" in segment:
            db_part, fields_part = segment.split(":", 1)
            db_id = db_part.strip().lower()
        else:
            continue

        if db_id not in result:
            continue

        catalog = APPENDIX_CATALOG.get(db_id, {})
        for token in fields_part.split(","):
            field = token.strip()
            if field in catalog:
                result[db_id].append(field)

    return result


def create_config_from_onboarding(
    db_root: str = "~/DB",
    enabled_dbs: Optional[List[str]] = None,
    appendix_fields: Optional[Dict[str, List[str]]] = None,
    base_dir: Optional[Path] = None,
) -> FathomConfig:
    """Create and save config from onboarding choices.

    Args:
        db_root: User-chosen DB root path.
        enabled_dbs: User-chosen DB list (None means all).
        appendix_fields: User-chosen appendix fields (None means empty).
        base_dir: Override fathom root for testing.

    Returns:
        The saved FathomConfig.
    """
    if enabled_dbs is None:
        enabled_dbs = list(DB_DISPLAY_NAMES.keys())

    if appendix_fields is None:
        appendix_fields = {db: [] for db in enabled_dbs}

    config = FathomConfig(
        db_root=db_root,
        enabled_dbs=enabled_dbs,
        appendix_fields=appendix_fields,
        language="ko",
        extended_provenance=False,
    )

    save_config(config, base_dir)
    return config
