#!/usr/bin/env python3
"""
크롤러 오케스트레이터 인벤토리 스크립트.
DB 크롤러 레지스트리 조회, 수집현황 확인, 크로스 DB 검색 수행.

Usage:
    python3 .claude/skills/crawl-orchestrator/scripts/inventory.py inventory
    python3 .claude/skills/crawl-orchestrator/scripts/inventory.py status [--source SOURCE] [--keyword KEYWORD]
    python3 .claude/skills/crawl-orchestrator/scripts/inventory.py search "검색어" [--title ...] [--body ...] [--creator ...]
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

try:
    import yaml
except ImportError:
    print("Error: PyYAML 필요. pip install pyyaml", file=sys.stderr)
    sys.exit(1)

def _get_db_root() -> Path:
    import os
    env = os.environ.get("KHC_DB_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    here = Path(__file__).resolve().parent
    for base in (here, *here.parents):
        cf = base / "crawl-orchestrator" / "config.json"
        if cf.is_file():
            try:
                c = json.loads(cf.read_text(encoding="utf-8"))
                raw = c.get("db_root", "")
                if raw:
                    p = Path(raw).expanduser()
                    return (p if p.is_absolute() else cf.parent / p).resolve()
            except Exception:
                pass
            return (cf.parent.parent / "DB").resolve()
    return Path.home() / "DB"


DB_ROOT = _get_db_root()
REGISTRY_PATH = DB_ROOT / "_registry.yaml"

# 번들로 간주하지 않는 디렉토리 패턴
SKIP_DIRS = {"_index", "_analysis", "_views", "_scripts", "__pycache__", "test", ".batch_temp"}


def load_registry():
    """레지스트리 YAML 파일 로드."""
    if REGISTRY_PATH.exists():
        with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    fallback = Path(__file__).resolve().parent.parent / "registry.default.yaml"
    if fallback.exists():
        with open(fallback, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    print(f"Error: 레지스트리 파일을 찾을 수 없음: {REGISTRY_PATH}", file=sys.stderr)
    print(f"  setup 명령으로 먼저 초기화하세요.", file=sys.stderr)
    sys.exit(1)


def cmd_inventory(args):
    """등록된 크롤러 인벤토리 출력."""
    reg = load_registry()
    sources = reg.get("sources", {})
    unimplemented = reg.get("unimplemented", {})

    # 테이블 헤더
    print("=" * 90)
    print("  등록된 크롤러 인벤토리")
    print("=" * 90)
    print()
    print(f"  {'소스':<12} {'이름':<25} {'플랫폼':<30} {'시대':<6} {'스킬':<20} {'모드'}")
    print(f"  {'-'*12} {'-'*25} {'-'*30} {'-'*6} {'-'*20} {'-'*15}")

    for key, src in sources.items():
        name = src.get("name", "?")
        platform = src.get("platform", "?")
        period = src.get("period", "?")
        skill = src.get("skill") or "(없음)"
        modes = ", ".join(src.get("modes", []))
        print(f"  {key:<12} {name:<25} {platform:<30} {period:<6} {skill:<20} {modes}")

    print()
    print(f"  총 {len(sources)}개 소스 등록됨")

    # 미구현 DB
    if unimplemented:
        print()
        print("-" * 90)
        print("  미구현 DB (향후 개별 크롤러 스킬 개발 대상)")
        print("-" * 90)
        print()
        for category, items in unimplemented.items():
            print(f"  [{category}]")
            for item in items:
                item_id = item.get("id", "?")
                name = item.get("name", "?")
                priority = item.get("priority", "")
                note = item.get("note", "")
                extra = []
                if priority:
                    extra.append(f"우선순위: {priority}")
                if note:
                    extra.append(note)
                extra_str = f" ({', '.join(extra)})" if extra else ""
                print(f"    {item_id:<8} {name}{extra_str}")
            print()


def match_bundle_keyword(bundle_path, keyword):
    """번들이 키워드와 매칭되는지 확인. 매칭 소스 반환 (없으면 None)."""
    keyword_lower = keyword.lower()
    
    # 1순위: metadata.json의 search_params.keywords
    meta_path = bundle_path / "metadata.json"
    if meta_path.exists():
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            search_params = meta.get("search_params", {})
            kw_list = search_params.get("keywords", [])
            if kw_list:
                for kw in kw_list:
                    if keyword_lower in kw.lower() or kw.lower() in keyword_lower:
                        return f"search_params.keywords: {kw}"
            # Munzip 구 스키마: 최상위 keywords 필드
            kw_list_old = meta.get("keywords", [])
            if kw_list_old:
                for kw in kw_list_old:
                    if keyword_lower in kw.lower() or kw.lower() in keyword_lower:
                        return f"metadata.keywords: {kw}"
        except (json.JSONDecodeError, KeyError):
            pass
    
    # 2순위: keywords.json (Munzip)
    kw_json = bundle_path / "keywords.json"
    if kw_json.exists():
        try:
            with open(kw_json, "r", encoding="utf-8") as f:
                kw_data = json.load(f)
            if isinstance(kw_data, list):
                for kw in kw_data:
                    if isinstance(kw, str) and (keyword_lower in kw.lower() or kw.lower() in keyword_lower):
                        return f"keywords.json: {kw}"
        except (json.JSONDecodeError, KeyError):
            pass
    
    # 3순위: 번들 디렉토리명 substring 매칭
    if keyword_lower in bundle_path.name.lower():
        return f"번들명: {bundle_path.name}"
    
    return None


def count_articles_in_bundle(bundle_path):
    """번들 내 기사 수를 세는 함수."""
    # 1순위: metadata.json의 total_articles (가장 빠름)
    meta_path = bundle_path / "metadata.json"
    if meta_path.exists():
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            total = meta.get("total_articles")
            if total is not None and isinstance(total, int):
                return total
        except (json.JSONDecodeError, KeyError):
            pass
    
    # 2순위: articles.json (기존 호환)
    articles_json = bundle_path / "articles.json"
    if articles_json.exists():
        try:
            with open(articles_json, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return len(data)
            elif isinstance(data, dict):
                return len(data)
        except (json.JSONDecodeError, MemoryError):
            pass

    # 3순위: raw/ 디렉토리의 JSON 파일 수
    raw_dir = bundle_path / "raw"
    if raw_dir.exists():
        return len(list(raw_dir.glob("*.json")))
    return 0


def get_last_modified(bundle_path):
    """번들의 가장 최근 수정일을 반환."""
    latest = 0
    # metadata.json 또는 articles.json의 mtime 확인
    for fname in ["metadata.json", "articles.json"]:
        fpath = bundle_path / fname
        if fpath.exists():
            mtime = fpath.stat().st_mtime
            if mtime > latest:
                latest = mtime
    if latest > 0:
        return datetime.fromtimestamp(latest).strftime("%Y-%m-%d %H:%M")
    return "?"


def cmd_status(args):
    """수집현황 출력."""
    reg = load_registry()
    sources = reg.get("sources", {})
    filter_source = args.source
    filter_keyword = getattr(args, 'keyword', None)

    if filter_keyword:
        print("=" * 80)
        print(f"  키워드 매칭 검색: '{filter_keyword}'")
        print("=" * 80)
        print()
        print(f"  {'소스':<14} {'번들명':<35} {'기사 수':>10} {'매칭':}")
        print(f"  {'-'*14} {'-'*35} {'-'*10} {'-'*30}")

        match_count = 0
        for key, src in sources.items():
            if filter_source and key != filter_source:
                continue
            raw_db_path = src.get("db_path", f"DB/{key}")
            sub_dir = raw_db_path.split("/", 1)[1] if "/" in raw_db_path else key
            db_path = DB_ROOT / sub_dir
            if not db_path.exists():
                continue
            for d in sorted(db_path.iterdir()):
                if not d.is_dir():
                    continue
                if d.name.startswith("_") or d.name.startswith(".") or d.name in SKIP_DIRS:
                    continue
                match_info = match_bundle_keyword(d, filter_keyword)
                if match_info:
                    ac = count_articles_in_bundle(d)
                    ac_str = f"{ac:,}" if ac > 0 else "0"
                    print(f"  {key:<14} {d.name:<35} {ac_str:>10} {match_info}")
                    match_count += 1

        print()
        if match_count == 0:
            print(f"  매칭되는 번들이 없습니다.")
        else:
            print(f"  총 {match_count}개 번들 매칭됨")
        print()
        return

    print("=" * 80)
    print("  수집현황")
    print("=" * 80)
    print()
    print(f"  {'소스':<14} {'번들 수':>8} {'총 기사 수':>12} {'최종 수집일':<20}")
    print(f"  {'-'*14} {'-'*8} {'-'*12} {'-'*20}")

    total_bundles = 0
    total_articles = 0

    for key, src in sources.items():
        if filter_source and key != filter_source:
            continue

        raw_db_path = src.get("db_path", f"DB/{key}")
        sub_dir = raw_db_path.split("/", 1)[1] if "/" in raw_db_path else key
        db_path = DB_ROOT / sub_dir
        if not db_path.exists():
            print(f"  {key:<14} {'(디렉토리 없음)':>8}")
            continue

        bundles = []
        for d in sorted(db_path.iterdir()):
            if not d.is_dir():
                continue
            if d.name.startswith("_") or d.name.startswith(".") or d.name in SKIP_DIRS:
                continue
            bundles.append(d)

        bundle_count = len(bundles)
        article_count = 0
        latest_date = "?"

        latest_ts = 0
        for b in bundles:
            article_count += count_articles_in_bundle(b)
            # 최종 수정일
            for fname in ["metadata.json", "articles.json"]:
                fpath = b / fname
                if fpath.exists():
                    mtime = fpath.stat().st_mtime
                    if mtime > latest_ts:
                        latest_ts = mtime

        if latest_ts > 0:
            latest_date = datetime.fromtimestamp(latest_ts).strftime("%Y-%m-%d %H:%M")

        total_bundles += bundle_count
        total_articles += article_count

        article_str = f"{article_count:,}" if article_count > 0 else "0"
        print(f"  {key:<14} {bundle_count:>8} {article_str:>12} {latest_date:<20}")

    print(f"  {'-'*14} {'-'*8} {'-'*12} {'-'*20}")
    print(f"  {'합계':<14} {total_bundles:>8} {total_articles:>12,}")
    print()

    # 상세 보기: --source가 있으면 번들별 내역 출력
    if filter_source and filter_source in sources:
        src = sources[filter_source]
        raw_db_path = src.get("db_path", f"DB/{filter_source}")
        sub_dir = raw_db_path.split("/", 1)[1] if "/" in raw_db_path else filter_source
        db_path = DB_ROOT / sub_dir
        if db_path.exists():
            print(f"  [{filter_source}] 번들 상세")
            print(f"  {'번들명':<35} {'기사 수':>10} {'최종 수집일':<20}")
            print(f"  {'-'*35} {'-'*10} {'-'*20}")

            for d in sorted(db_path.iterdir()):
                if not d.is_dir():
                    continue
                if d.name.startswith("_") or d.name.startswith(".") or d.name in SKIP_DIRS:
                    continue
                ac = count_articles_in_bundle(d)
                lm = get_last_modified(d)
                ac_str = f"{ac:,}" if ac > 0 else "0"
                print(f"  {d.name:<35} {ac_str:>10} {lm:<20}")
            print()


def cmd_search(args):
    """db.history.go.kr 통합검색 실행."""
    try:
        import requests
    except ImportError:
        print("Error: requests 필요. pip install requests", file=sys.stderr)
        sys.exit(1)

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        print("Error: beautifulsoup4 필요. pip install beautifulsoup4", file=sys.stderr)
        sys.exit(1)

    keyword = args.keyword
    if not keyword:
        print("Error: 검색어를 입력하세요.", file=sys.stderr)
        sys.exit(1)

    # POST 파라미터 구성
    params = {
        "totalWord": keyword,
        "pageIndex": "1",
        "pageUnit": "20",
        "chinessChar": "on",
    }
    if args.title:
        params["titleWord"] = args.title
    if args.body:
        params["contentsWord"] = args.body
    if args.creator:
        params["creatorWord"] = args.creator
    if args.date_from:
        params["startDate"] = args.date_from
    if args.date_to:
        params["endDate"] = args.date_to
    if args.items:
        params["searchItemId"] = args.items

    url = "https://db.history.go.kr/search/searchTotalResult.do"

    print(f"  검색 중: '{keyword}' ...")
    print()

    try:
        resp = requests.post(url, data=params, timeout=30, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://db.history.go.kr/search/searchTotalResult.do",
        })
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"Error: 검색 요청 실패 — {e}", file=sys.stderr)
        sys.exit(1)

    soup = BeautifulSoup(resp.text, "html.parser")

    # 총 건수: .search-result-top .num
    total_el = soup.select_one(".search-result-top .num")
    total_count = total_el.get_text(strip=True) if total_el else "?"

    # 시대별 섹션 + 개별 DB 파싱
    # 구조: section > .title > .tit > .txt (시대명), .num b (시대 건수)
    #        section > ul.list-wrap > li > a (DB명 + div.num > span 건수)
    sections = soup.select(".search-result-content section")

    if sections:
        print("=" * 70)
        print(f"  db.history.go.kr 통합검색 결과: '{keyword}'")
        print(f"  총 {total_count}건")
        print("=" * 70)
        print()
        print(f"  {'#':>4}  {'DB명':<40} {'ID':<10} {'건수':>8}")
        print(f"  {'-'*4}  {'-'*40} {'-'*10} {'-'*8}")

        idx = 0
        for section in sections:
            # 시대명 + 시대 건수
            era_name_el = section.select_one(".title .tit .txt")
            era_count_el = section.select_one(".title .tit .num b")
            era_name = era_name_el.get_text(strip=True) if era_name_el else "?"
            era_count = era_count_el.get_text(strip=True) if era_count_el else "?"
            print(f"       {era_name} ({era_count}건)")

            # 개별 DB
            items = section.select("ul.list-wrap li a")
            for item in items:
                idx += 1
                # DB명: <a> 텍스트에서 건수 div 제외하고 직접 텍스트만 추출
                from bs4.element import NavigableString
                db_name = ""
                for child in item.children:
                    if isinstance(child, NavigableString):
                        db_name += child.strip()
                db_name = db_name.strip()

                # 건수
                count_el = item.select_one("div.num span")
                count_text = count_el.get_text(strip=True) if count_el else "?"

                # itemId: onclick에서 추출
                onclick = item.get("onclick", "")
                item_id = ""
                if "fnGoSearchResultItem" in onclick:
                    # fnGoSearchResultItem('diachronic', 'hb')
                    parts = onclick.split("'")
                    if len(parts) >= 4:
                        item_id = parts[3]

                print(f"  {idx:>4}  {db_name:<40} {item_id:<10} {count_text:>8}")

            print()

        print(f"  {'':>4}  {'합계':<40} {'':10} {total_count:>8}")
    else:
        title = soup.select_one("title")
        title_text = title.get_text(strip=True) if title else "(제목 없음)"

        print("=" * 70)
        print(f"  db.history.go.kr 통합검색: '{keyword}'")
        print("=" * 70)
        print()
        print(f"  페이지 제목: {title_text}")
        print(f"  총 건수: {total_count}")
        print()
        print("  [참고] HTML 파싱에 실패했을 수 있습니다.")
        print("  실제 결과는 https://db.history.go.kr 에서 직접 확인하세요.")
        print()
        debug_path = DB_ROOT / ".search_debug.html"
        with open(debug_path, "w", encoding="utf-8") as f:
            f.write(resp.text)
        print(f"  디버깅용 HTML 저장: {debug_path}")

    # 참고 안내
    print()
    print("  [참고] 별도 도메인 DB는 통합검색에 포함되지 않습니다:")
    print("    - 조선왕조실록 → sillok-crawler 스킬의 search 기능 사용")
    print("    - 승정원일기 → sjw-crawler 스킬의 search 기능 사용")
    print("    - 한국고전종합DB → munzip-crawler 스킬의 search 기능 사용")
    print("    - 뉴스 라이브러리 → newslibrary-crawler 스킬의 search 기능 사용")


def cmd_setup(args):
    """DB 저장 경로 설정 → config.json 생성."""
    config_dir = Path(__file__).resolve().parent.parent
    config_path = config_dir / "config.json"
    default_path = config_dir / "config.default.json"

    print("=" * 60)
    print("  크롤러 DB 저장 경로 설정")
    print("=" * 60)
    print()

    current = {}
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            current = json.load(f)
        current_root = current.get("db_root", "")
        if current_root:
            print(f"  현재 설정: {current_root}")
        else:
            print(f"  현재 설정: (기본 경로 — 프로젝트 루트/DB)")
        print()

    if args.db_root is not None:
        db_root = args.db_root
    else:
        print("  DB를 저장할 경로를 입력하세요.")
        print("  비워두면 기본 경로(프로젝트 루트/DB)를 사용합니다.")
        print()
        db_root = input("  DB 경로: ").strip()

    config = {"db_root": db_root}
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print()
    if db_root:
        resolved = Path(db_root).expanduser().resolve()
        print(f"  ✅ 설정 완료: {resolved}")
        if not resolved.exists():
            print(f"  ⚠️  경로가 아직 존재하지 않습니다. 크롤링 시 자동 생성됩니다.")
    else:
        print(f"  ✅ 기본 경로 사용으로 설정")

    print(f"  설정 파일: {config_path}")


def cmd_update(args):
    """스킬 업데이트 (git pull)."""
    skills_dir = Path(__file__).resolve().parent.parent.parent
    print("=" * 60)
    print("  크롤러 스킬 업데이트")
    print("=" * 60)
    print()

    git_dir = skills_dir
    while git_dir != git_dir.parent:
        if (git_dir / ".git").exists():
            break
        git_dir = git_dir.parent
    else:
        print("  ❌ git 저장소를 찾을 수 없습니다.")
        sys.exit(1)

    print(f"  저장소: {git_dir}")
    print()

    try:
        result = subprocess.run(
            ["git", "pull", "--ff-only"],
            cwd=str(git_dir),
            capture_output=True,
            text=True,
            timeout=30,
        )
        print(result.stdout)
        if result.returncode != 0:
            print(f"  ⚠️  git pull 실패:", file=sys.stderr)
            print(result.stderr, file=sys.stderr)
            sys.exit(1)
        print("  ✅ 업데이트 완료")
    except FileNotFoundError:
        print("  ❌ git이 설치되어 있지 않습니다.", file=sys.stderr)
        sys.exit(1)
    except subprocess.TimeoutExpired:
        print("  ❌ git pull 타임아웃 (30초)", file=sys.stderr)
        sys.exit(1)


def cmd_check_deps(args):
    """필수 패키지 설치 상태 확인."""
    print("=" * 60)
    print("  필수 패키지 확인")
    print("=" * 60)
    print()

    deps = [
        ("requests", "requests", "모든 크롤러"),
        ("bs4", "beautifulsoup4", "HTML 파싱"),
        ("yaml", "pyyaml", "오케스트레이터"),
    ]

    optional_deps = [
        ("playwright", "playwright", "뉴스라이브러리 인증"),
    ]

    all_ok = True
    print(f"  {'패키지':<20} {'pip 이름':<20} {'상태':<8} {'용도'}")
    print(f"  {'-'*20} {'-'*20} {'-'*8} {'-'*20}")

    for mod_name, pip_name, usage in deps:
        try:
            __import__(mod_name)
            status = "✅"
        except ImportError:
            status = "❌"
            all_ok = False
        print(f"  {mod_name:<20} {pip_name:<20} {status:<8} {usage}")

    print()
    print("  [선택 패키지]")
    for mod_name, pip_name, usage in optional_deps:
        try:
            __import__(mod_name)
            status = "✅"
        except ImportError:
            status = "⚠️ 미설치"
        print(f"  {mod_name:<20} {pip_name:<20} {status:<8} {usage}")

    print()
    if all_ok:
        print("  ✅ 필수 패키지 모두 설치됨")
    else:
        print("  ❌ 미설치 패키지가 있습니다. 아래 명령으로 설치:")
        missing = [pip_name for mod_name, pip_name, _ in deps
                   if not _try_import(mod_name)]
        print(f"    pip install {' '.join(missing)}")

    try:
        import playwright  # noqa: F811
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "--dry-run", "chromium"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            print()
            print("  ⚠️  playwright chromium 브라우저 미설치")
            print("    python -m playwright install chromium")
    except (ImportError, FileNotFoundError, subprocess.TimeoutExpired):
        pass


def _try_import(mod_name: str) -> bool:
    try:
        __import__(mod_name)
        return True
    except ImportError:
        return False


def main():
    parser = argparse.ArgumentParser(
        description="크롤러 오케스트레이터 인벤토리",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="서브커맨드")

    # inventory
    sub_inv = subparsers.add_parser("inventory", help="등록된 크롤러 인벤토리 출력")

    # status
    sub_status = subparsers.add_parser("status", help="수집현황 출력")
    sub_status.add_argument("--source", help="특정 소스만 조회 (예: sillok)")
    sub_status.add_argument("--keyword", help="키워드로 매칭 번들 검색")

    # search
    sub_search = subparsers.add_parser("search", help="db.history.go.kr 크로스 DB 검색")
    sub_search.add_argument("keyword", help="검색어")
    sub_search.add_argument("--title", help="제목 검색어")
    sub_search.add_argument("--body", help="본문 검색어")
    sub_search.add_argument("--creator", help="저자 검색어")
    sub_search.add_argument("--date-from", help="시작일 (YYYYMMDD)")
    sub_search.add_argument("--date-to", help="종료일 (YYYYMMDD)")
    sub_search.add_argument("--items", help="특정 DB만 (쉼표 구분, 예: bb,ks)")
    sub_search.add_argument("--count-only", action="store_true", default=True, help="건수만 출력 (기본)")

    # setup
    sub_setup = subparsers.add_parser("setup", help="DB 저장 경로 설정")
    sub_setup.add_argument("--db-root", dest="db_root", default=None,
                           help="DB 저장 경로 (비대화형 모드)")

    # update
    sub_update = subparsers.add_parser("update", help="스킬 업데이트 (git pull)")

    # check-deps
    sub_deps = subparsers.add_parser("check-deps", help="필수 패키지 설치 확인")

    args = parser.parse_args()

    if args.command == "inventory":
        cmd_inventory(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "search":
        cmd_search(args)
    elif args.command == "setup":
        cmd_setup(args)
    elif args.command == "update":
        cmd_update(args)
    elif args.command == "check-deps":
        cmd_check_deps(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
