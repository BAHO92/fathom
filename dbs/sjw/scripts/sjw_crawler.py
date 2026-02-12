#!/usr/bin/env python3
"""
승정원일기 크롤링 스크립트 (sjw_crawler.py)
승정원일기 사이트에서 기사를 수집하여 JSON으로 저장
국역은 한국고전종합DB(ITKC)에서 추출

Usage:
    # A모드: 검색 결과 파일 기반
    python sjw_crawler.py <input.json> --name <collection_name>

    # B모드: 날짜 범위 열람
    python sjw_crawler.py browse --reign 현종 --name 현종_전체
    python sjw_crawler.py browse --reign 숙종 --year-from 20 --year-to 25 --name 숙종_20_25년

Input file format (JSON, from sjw_search.py):
    {
        "metadata": {...},
        "entries": [
            {"id": "SJW-A04060010-00100", "date": "...", "title": "...", "url": "..."}
        ]
    }

Output:
    DB/SJW/{collection_name}/
        ├── raw/              # 기사별 개별 JSON
        ├── metadata.json     # 수집 메타정보
        └── failed_articles.json  # 실패 로그 (실패 시)
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

# 패키지 설치 확인
def check_and_install_packages():
    required = {
        'requests': 'requests',
        'bs4': 'beautifulsoup4'
    }
    for pkg, pip_name in required.items():
        try:
            __import__(pkg)
        except ImportError:
            print(f"Installing {pip_name}...")
            import subprocess
            subprocess.check_call([sys.executable, "-m", "pip", "install", pip_name])

check_and_install_packages()

import requests
from bs4 import BeautifulSoup

# 글로벌 변수
print_lock = Lock()
progress_lock = Lock()
processed_count = 0
total_count = 0
crawl_mode = "search"
search_keywords = []
browse_reign = ""
browse_year_range = (None, None)

# DB 경로
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
            return (base / "DB").resolve()
    return Path.home() / "DB"

DB_PATH = _get_db_root() / "SJW"

# 사이트 설정
SJW_BASE = "https://sjw.history.go.kr"
ITKC_BASE = "https://db.itkc.or.kr"

# HTTP 설정
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# 왕코드 매핑
KING_CODES = {
    'A': '인조', 'B': '효종', 'C': '현종', 'D': '숙종',
    'E': '경종', 'F': '영조', 'G': '정조', 'H': '순조',
    'I': '헌종', 'J': '철종', 'K': '고종', 'L': '순종'
}

KING_NAMES_TO_CODES = {v: k for k, v in KING_CODES.items()}


def safe_print(*args, **kwargs):
    """스레드 안전 출력"""
    with print_lock:
        print(*args, **kwargs, flush=True)


def create_session() -> requests.Session:
    """HTTP 세션 생성"""
    session = requests.Session()
    session.headers.update({
        'User-Agent': USER_AGENT,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
    })
    return session


# =============================================================================
# B모드: 날짜 범위 열람 (기사 ID 수집)
# =============================================================================

def browse_get_months(session: requests.Session, king_code: str,
                      king_name: str) -> list[str]:
    """
    inspectionMonthList에서 왕대의 월 목록 수집

    Args:
        king_code: 왕 코드 (A-L)
        king_name: 왕 이름 (인조, 효종, ...)

    Returns:
        월 ID 목록 (예: ['SJW-C00050', 'SJW-C00060', ...])
    """
    url = f"{SJW_BASE}/search/inspectionMonthList.do"
    data = {
        'treeID': f'SJW-{king_code}',
        'treeLevel': '1',
        'treeType': '왕대별',
        'treeKingName': king_name
    }

    resp = session.post(url, data=data, timeout=30)
    # 월 ID 패턴: SJW-C{YYMM}0 (뒤에 -이 안 붙는 것)
    pattern = re.compile(rf'SJW-{king_code}\d{{4}}0(?![\d-])')
    month_ids = sorted(set(pattern.findall(resp.text)))
    return month_ids


def browse_get_day_ids(session: requests.Session, month_id: str,
                       king_name: str) -> list[str]:
    """
    inspectionDayList에서 월의 일 목록 수집

    Returns:
        일 ID 목록 (예: ['SJW-C00060010', 'SJW-C00060020', ...])
    """
    url = f"{SJW_BASE}/search/inspectionDayList.do"
    data = {
        'treeID': month_id,
        'treeLevel': '3',
        'treeKingName': king_name
    }

    resp = session.post(url, data=data, timeout=30)
    king_code = month_id[4]
    pattern = re.compile(rf'SJW-{king_code}\d{{7}}0(?![\d-])')
    day_ids = sorted(set(pattern.findall(resp.text)))
    return day_ids


def browse_get_article_ids(session: requests.Session,
                           day_id: str) -> list[dict]:
    """
    일(日) 페이지에서 해당 일의 기사 ID + 제목 추출

    Args:
        day_id: 일 ID (예: SJW-C00060010)

    Returns:
        [{'id': 'SJW-C00060010-00100', 'title': '...'}, ...]
    """
    url = f"{SJW_BASE}/id/{day_id}"
    resp = session.get(url, timeout=30)
    soup = BeautifulSoup(resp.text, 'html.parser')

    entries = []
    # TITLE_ 요소에서 해당 일의 기사만 추출
    for title_elem in soup.select('[id^="TITLE_"]'):
        elem_id = title_elem.get('id', '')
        article_id = elem_id.replace('TITLE_', '')
        # 해당 일의 기사만 (day_id로 시작하는 것)
        if article_id.startswith(day_id[:14]):
            title_text = title_elem.get_text(strip=True)
            entries.append({
                'id': article_id,
                'title': title_text,
                'url': f"{SJW_BASE}/id/{article_id}"
            })

    return entries


def browse_collect_entries(reign: str, year_from: int = None,
                           year_to: int = None) -> list[dict]:
    """
    날짜 범위로 기사 ID 목록 수집

    Args:
        reign: 왕대명 (현종, 숙종, ...)
        year_from: 시작 년 (0=즉위년, None=전체)
        year_to: 종료 년 (None=전체)

    Returns:
        기사 엔트리 목록 (sjw_crawler A모드 입력과 호환)
    """
    king_code = KING_NAMES_TO_CODES.get(reign)
    if not king_code:
        print(f"오류: 유효하지 않은 왕대명 '{reign}'")
        print(f"  가능한 왕대: {', '.join(KING_NAMES_TO_CODES.keys())}")
        sys.exit(1)

    session = create_session()

    # 세션 수립
    session.get(f"{SJW_BASE}/search/detailSearch.do", timeout=30)

    # 1단계: 월 목록 수집
    print(f"[1/3] {reign} 월 목록 수집 중...")
    month_ids = browse_get_months(session, king_code, reign)
    print(f"  전체 월 수: {len(month_ids)}")

    # 년도 필터링
    if year_from is not None or year_to is not None:
        yf = year_from if year_from is not None else 0
        yt = year_to if year_to is not None else 99
        filtered = []
        for mid in month_ids:
            # SJW-C{YY}{MM}0 → year = int(mid[5:7])
            year_val = int(mid[5:7])
            if yf <= year_val <= yt:
                filtered.append(mid)
        month_ids = filtered
        print(f"  필터링 후: {len(month_ids)}개월 ({yf}년~{yt}년)")

    if not month_ids:
        print("해당 기간에 월 데이터가 없습니다.")
        return []

    # 2단계: 각 월의 일 목록 수집
    print(f"\n[2/3] 일 목록 수집 중...")
    all_day_ids = []
    for i, mid in enumerate(month_ids):
        day_ids = browse_get_day_ids(session, mid, reign)
        all_day_ids.extend(day_ids)
        if (i + 1) % 20 == 0 or i == len(month_ids) - 1:
            print(f"  [{i+1}/{len(month_ids)}] 월 처리, 누적 일수: {len(all_day_ids)}")
        time.sleep(0.2)

    print(f"  총 일수: {len(all_day_ids)}")

    # 3단계: 각 일의 기사 ID 수집
    print(f"\n[3/3] 기사 ID 수집 중...")
    all_entries = []
    for i, day_id in enumerate(all_day_ids):
        entries = browse_get_article_ids(session, day_id)
        all_entries.extend(entries)
        if (i + 1) % 50 == 0 or i == len(all_day_ids) - 1:
            print(f"  [{i+1}/{len(all_day_ids)}] 일 처리, 누적 기사: {len(all_entries)}")
        time.sleep(0.2)

    print(f"\n기사 ID 수집 완료: {len(all_entries)}건")
    session.close()
    return all_entries


# =============================================================================
# 입력 파일 파싱
# =============================================================================

def parse_input_file(filepath: str) -> list[dict]:
    """JSON 입력 파일 파싱 (sjw_search.py 출력 형식)"""
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # sjw_search.py 출력 형식: {'metadata': {...}, 'entries': [...]}
    if 'entries' in data:
        raw_entries = data['entries']
    elif isinstance(data, list):
        raw_entries = data
    else:
        raw_entries = []

    entries = []
    for item in raw_entries:
        entry = {
            'id': item.get('id', ''),
            'date_str': item.get('date', ''),
            'title': item.get('title', ''),
            'url': item.get('url', f"{SJW_BASE}/id/{item.get('id', '')}")
        }
        entries.append(entry)

    return entries


# =============================================================================
# 기사 ID에서 메타데이터 추출
# =============================================================================

def parse_article_id(article_id: str) -> dict:
    """
    기사 ID에서 날짜 정보 추출

    SJW-{왕코드}{년2}{월2}{일3}{0}-{기사번호5}
    예: SJW-A04060010-00100 → 인조 4년 6월 1일, 기사 1
        SJW-K21080040-01200 → 고종 21년 8월 4일, 기사 12
    """
    result = {
        'reign': '',
        'year': 0,
        'month': 0,
        'day': 0,
        'ganzhi': '',
        'article_num': 1
    }

    match = re.match(r'^SJW-([A-L])(\d{2})(\d{2})(\d{3})(\d)-(\d{5})$', article_id)
    if match:
        king_code = match.group(1)
        result['reign'] = KING_CODES.get(king_code, '')
        result['year'] = int(match.group(2))
        result['month'] = int(match.group(3))
        result['day'] = int(match.group(4))
        # 기사번호: 00100 → 1, 01200 → 12
        article_num_raw = int(match.group(6))
        result['article_num'] = article_num_raw // 100

    return result


def parse_source_info(source_text: str) -> dict:
    """
    출전/날짜 문자열 파싱

    예: "승정원일기 13책 (탈초본 1책)  인조 4년 6월 1일 임신 2/2 기사
         1626년  天啓(明/熹宗) 6년"
    """
    result = {
        'book_num': 0,
        'book_num_talcho': 0,
        'source_info': '',
        'reign': '',
        'year': 0,
        'month': 0,
        'day': 0,
        'ganzhi': '',
        'article_num': 1,
        'total_articles': 0,
        'western_year': 0,
        'chinese_era': ''
    }

    if not source_text:
        return result

    # 책수
    book_match = re.search(r'승정원일기\s+(\d+)책', source_text)
    if book_match:
        result['book_num'] = int(book_match.group(1))

    # 탈초본 책수
    talcho_match = re.search(r'탈초본\s+(\d+)책', source_text)
    if talcho_match:
        result['book_num_talcho'] = int(talcho_match.group(1))

    # 출전 정보 (첫 줄)
    first_line = source_text.split('\n')[0].strip()
    source_info_match = re.match(r'(승정원일기\s+\d+책\s+\(탈초본\s+\d+책\))', first_line)
    if source_info_match:
        result['source_info'] = source_info_match.group(1)

    # 왕대/연월일
    reign_match = re.search(r'(인조|효종|현종|숙종|경종|영조|정조|순조|헌종|철종|고종|순종)\s+(\d+)년\s+(\d+)월\s+(\d+)일', source_text)
    if reign_match:
        result['reign'] = reign_match.group(1)
        result['year'] = int(reign_match.group(2))
        result['month'] = int(reign_match.group(3))
        result['day'] = int(reign_match.group(4))

    # 간지
    ganzhi_pattern = r'[甲乙丙丁戊己庚辛壬癸갑을병정무기경신임계][子丑寅卯辰巳午未申酉戌亥자축인묘진사오미신유술해]'
    ganzhi_match = re.search(ganzhi_pattern, source_text)
    if ganzhi_match:
        result['ganzhi'] = ganzhi_match.group(0)

    # 기사번호/총기사수 (예: "2/2 기사")
    num_match = re.search(r'(\d+)/(\d+)\s*기사', source_text)
    if num_match:
        result['article_num'] = int(num_match.group(1))
        result['total_articles'] = int(num_match.group(2))

    # 서기 연도
    western_match = re.search(r'(\d{4})년', source_text)
    if western_match:
        result['western_year'] = int(western_match.group(1))

    # 중국 연호
    era_match = re.search(r'(\S+)\(([^)]+)\)\s+\d+년', source_text)
    if era_match:
        result['chinese_era'] = f"{era_match.group(1)}({era_match.group(2)})"

    return result


# =============================================================================
# 기사 내용 크롤링
# =============================================================================

def extract_itkc_data_id(soup: BeautifulSoup) -> str:
    """SJW 기사 페이지에서 ITKC 국역 dataId 추출"""
    for btn in soup.select('button.origin-btn'):
        onclick = btn.get('onclick', '')
        text = btn.get_text(strip=True)
        if '국역' in text:
            match = re.search(r'dataId=(ITKC_ST_[^\'"&]+)', onclick)
            if match:
                return match.group(1)
    return ''


def fetch_translation(session: requests.Session, itkc_data_id: str, retry: int = 3) -> dict:
    """
    ITKC에서 국역 텍스트 추출

    Args:
        itkc_data_id: ITKC 자료ID (예: ITKC_ST_P0_A04_06A_01A_00020)
    """
    result = {
        'translation': '',
        'translation_title': ''
    }

    if not itkc_data_id:
        return result

    url = f"{ITKC_BASE}/dir/node?dataId={itkc_data_id}"

    for attempt in range(retry):
        try:
            response = session.get(url, timeout=30)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')

            # 제목
            title_elem = soup.select_one('div.text_body_tit h4')
            if title_elem:
                result['translation_title'] = title_elem.get_text(strip=True)

            # 번역문 (xsl_para)
            paragraphs = []
            for para in soup.select('div.text_body div.xsl_para, div.text_body div.xsl_para_tit'):
                text = para.get_text(strip=True)
                if text:
                    paragraphs.append(text)

            if paragraphs:
                result['translation'] = '\n\n'.join(paragraphs)

            return result

        except Exception as e:
            if attempt < retry - 1:
                time.sleep(1 * (attempt + 1))
            else:
                return result

    return result


def fetch_article(session: requests.Session, article_id: str, retry: int = 3) -> dict:
    """
    SJW 기사 페이지에서 원문 + ITKC 국역 추출

    Args:
        article_id: 기사 ID (예: SJW-A04060010-00100)
    """
    result = {
        'title': '',
        'original': '',
        'translation': '',
        'has_translation': False,
        'itkc_data_id': '',
        'source_info': {},
        'date_info': {}
    }

    url = f"{SJW_BASE}/id/{article_id}"

    for attempt in range(retry):
        try:
            response = session.get(url, timeout=30)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')

            # 1. 기사 제목
            title_elem = soup.select_one(f'[id^="TITLE_"]')
            if title_elem:
                result['title'] = title_elem.get_text(strip=True)

            # 2. 원문 추출
            paragraphs = []
            for para in soup.select('div.view-area div.view-item p.paragraph'):
                text = para.get_text(strip=True)
                if text:
                    paragraphs.append(text)
            result['original'] = '\n\n'.join(paragraphs)

            # 3. 출전/날짜 정보
            source_elem = soup.select_one('div.title-head div.title p')
            if source_elem:
                source_text = source_elem.get_text(strip=True)
                result['source_info'] = parse_source_info(source_text)

            # 4. ITKC 국역 링크 추출
            itkc_data_id = extract_itkc_data_id(soup)
            result['itkc_data_id'] = itkc_data_id

            # 5. ITKC에서 국역 수집
            if itkc_data_id:
                time.sleep(0.3)  # ITKC rate limiting
                trans = fetch_translation(session, itkc_data_id)
                if trans['translation']:
                    result['translation'] = trans['translation']
                    result['has_translation'] = True

            return result

        except Exception as e:
            if attempt < retry - 1:
                time.sleep(1 * (attempt + 1))
            else:
                return {
                    'title': '',
                    'original': '[크롤링 실패]',
                    'translation': '',
                    'has_translation': False,
                    'itkc_data_id': '',
                    'source_info': {},
                    'date_info': {},
                    'error': str(e)
                }

    return result


# =============================================================================
# 워커 및 크롤링 오케스트레이션
# =============================================================================

def fetch_article_task(task: dict) -> dict:
    """워커용: 단일 기사 크롤링"""
    global processed_count, total_count

    session = create_session()

    try:
        article_id = task['id']
        content = fetch_article(session, article_id)

        with progress_lock:
            processed_count += 1
            current = processed_count

        title_preview = (content['title'] or task.get('title', ''))[:40]
        trans_mark = '✓' if content.get('has_translation') else '✗'
        safe_print(f"[{current}/{total_count}] {trans_mark} {title_preview}...")

        # 날짜 정보: 출전에서 파싱한 것 우선, 없으면 ID에서 추출
        if content.get('source_info') and content['source_info'].get('reign'):
            date_info = {
                'reign': content['source_info']['reign'],
                'year': content['source_info']['year'],
                'month': content['source_info']['month'],
                'day': content['source_info']['day'],
                'ganzhi': content['source_info']['ganzhi'],
                'article_num': content['source_info']['article_num']
            }
        else:
            date_info = parse_article_id(article_id)

        # 출전 정보
        src = content.get('source_info', {})
        source = {
            'book_num': src.get('book_num', 0),
            'book_num_talcho': src.get('book_num_talcho', 0),
            'source_info': src.get('source_info', '')
        }

        article = {
            'id': article_id,
            'title': content['title'] or task.get('title', ''),
            'date': date_info,
            'article_num': date_info.get('article_num', 1),
            'source': source,
            'url': f"{SJW_BASE}/id/{article_id}",
            'original': content.get('original', ''),
            'translation': content.get('translation', ''),
            'has_translation': content.get('has_translation', False),
            'source_specific': {
                'itkc_data_id': content.get('itkc_data_id', '')
            }
        }

        # 크롤링 실패 체크
        if content.get('error') or content['original'] == '[크롤링 실패]':
            return {
                'article': None,
                'success': False,
                'error': {
                    'id': article_id,
                    'url': f"{SJW_BASE}/id/{article_id}",
                    'title': task.get('title', ''),
                    'error_type': 'FetchError',
                    'error_message': content.get('error', 'Unknown error'),
                    'timestamp': datetime.now().isoformat()
                }
            }

        return {
            'article': article,
            'success': True
        }

    except Exception as e:
        safe_print(f"Error fetching {task.get('id', 'unknown')}: {e}")
        return {
            'article': None,
            'success': False,
            'error': {
                'id': task.get('id', 'unknown'),
                'url': task.get('url', 'unknown'),
                'title': task.get('title', 'unknown'),
                'error_type': type(e).__name__,
                'error_message': str(e),
                'timestamp': datetime.now().isoformat()
            }
        }


def crawl_articles(entries: list[dict], collection_name: str, num_workers: int = 4,
                   resume: bool = False):
    """기사들 크롤링"""
    global processed_count, total_count

    # 출력 디렉토리 설정
    output_dir = DB_PATH / collection_name
    raw_dir = output_dir / "raw"
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(exist_ok=True)

    # 진행 파일
    progress_file = output_dir / ".progress.json"

    # 재개 모드
    completed_ids = set()
    if resume:
        if progress_file.exists():
            with open(progress_file, 'r', encoding='utf-8') as f:
                progress_data = json.load(f)
                completed_ids = set(progress_data.get('completed_ids', []))
        for json_file in raw_dir.glob("*.json"):
            completed_ids.add(json_file.stem)
        if completed_ids:
            print(f"Resuming: {len(completed_ids)} entries already completed", flush=True)

    # 남은 작업 필터링
    remaining = [e for e in entries if e['id'] not in completed_ids]
    total_count = len(remaining)
    processed_count = 0

    print(f"\nProcessing {len(remaining)} entries with {num_workers} workers...", flush=True)
    print(f"(✓=국역 있음, ✗=원문만)")

    # 기존 결과 로드
    articles = []
    failed_articles = []
    if resume:
        for json_file in raw_dir.glob("*.json"):
            with open(json_file, 'r', encoding='utf-8') as f:
                articles.append(json.load(f))

    # 병렬 크롤링
    if remaining:
        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = {executor.submit(fetch_article_task, e): e for e in remaining}

            for future in as_completed(futures):
                result = future.result()
                if result['success'] and result['article']:
                    article = result['article']
                    articles.append(article)
                    completed_ids.add(article['id'])

                    # 개별 JSON 저장
                    article_file = raw_dir / f"{article['id']}.json"
                    with open(article_file, 'w', encoding='utf-8') as f:
                        json.dump(article, f, ensure_ascii=False, indent=2)

                    # 주기적으로 진행 상황 저장
                    if len(completed_ids) % 10 == 0:
                        with open(progress_file, 'w', encoding='utf-8') as f:
                            json.dump({'completed_ids': list(completed_ids)}, f)
                else:
                    if 'error' in result:
                        failed_articles.append(result['error'])

    # 최종 저장 — 날짜순 정렬
    articles.sort(key=lambda a: (
        a['date'].get('year', 0),
        a['date'].get('month', 0),
        a['date'].get('day', 0),
        a.get('article_num', 0)
    ))

    trans_count = sum(1 for a in articles if a.get('has_translation'))

    reign_set = set()
    for a in articles:
        if a.get('date', {}).get('reign'):
            reign_set.add(a['date']['reign'])

    sorted_reign_list = sorted(reign_set, key=lambda r: list(KING_NAMES_TO_CODES.keys()).index(r) if r in KING_NAMES_TO_CODES else 99)

    metadata = {
        'collection_name': collection_name,
        'crawl_date': datetime.now().isoformat(),
        'total_articles': len(articles),
        'articles_with_translation': trans_count,
        'source': 'sjw',
        'crawl_mode': crawl_mode,
        'search_params': {'keywords': search_keywords} if crawl_mode == 'search' else {},
        'date_range': {
            'start': sorted_reign_list[0] if sorted_reign_list else None,
            'end': sorted_reign_list[-1] if sorted_reign_list else None
        },
        'source_detail': [],
        'preprocessing_done': False
    }

    metadata_file = output_dir / "metadata.json"
    with open(metadata_file, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    # 진행 파일 삭제
    if progress_file.exists():
        progress_file.unlink()

    # 실패 로그 저장
    if failed_articles:
        failed_file = output_dir / "failed_articles.json"
        with open(failed_file, 'w', encoding='utf-8') as f:
            json.dump(failed_articles, f, ensure_ascii=False, indent=2)
        print(f"\n⚠️  {len(failed_articles)}개 기사 크롤링 실패 - failed_articles.json 참조")

    print(f"\nSaved {len(articles)} articles to {output_dir}")
    print(f"  - raw/: 기사별 개별 JSON ({len(articles)}개)")
    print(f"  - metadata.json: 수집 메타정보")
    print(f"  - 국역 포함: {trans_count}/{len(articles)}건 ({trans_count*100//len(articles) if articles else 0}%)")
    if failed_articles:
        print(f"  - failed_articles.json: 실패 로그 ({len(failed_articles)}건)")

    return output_dir


# =============================================================================
# CLI
# =============================================================================

def main():
    global crawl_mode, search_keywords, browse_reign, browse_year_range
    is_browse = len(sys.argv) > 1 and sys.argv[1] == 'browse'

    if is_browse:
        # B모드: 날짜 범위 열람
        parser = argparse.ArgumentParser(
            description='승정원일기 크롤링 - B모드 (날짜 범위 열람)',
            prog='sjw_crawler.py browse'
        )
        parser.add_argument('--reign', required=True,
                            help=f'왕대명 ({", ".join(KING_NAMES_TO_CODES.keys())})')
        parser.add_argument('--year-from', '-yf', type=int, help='시작 년 (0=즉위년)')
        parser.add_argument('--year-to', '-yt', type=int, help='종료 년')
        parser.add_argument('--name', '-n', required=True, help='컬렉션 이름')
        parser.add_argument('--workers', '-w', type=int, default=4, help='병렬 워커 수 (기본: 4)')
        parser.add_argument('--resume', '-r', action='store_true', help='중단된 작업 재개')
        parser.add_argument('--limit', '-l', type=int, help='수집 건수 제한 (테스트용)')

        args = parser.parse_args(sys.argv[2:])

        crawl_mode = "browse"
        browse_reign = args.reign
        browse_year_range = (args.year_from, args.year_to)

        print(f"B모드: {args.reign} 열람 크롤링")
        if args.year_from is not None or args.year_to is not None:
            yf = args.year_from if args.year_from is not None else 0
            yt = args.year_to if args.year_to is not None else '끝'
            print(f"  연도 범위: {yf}년 ~ {yt}년")
        print()

        entries = browse_collect_entries(
            args.reign,
            year_from=args.year_from,
            year_to=args.year_to
        )
    else:
        # A모드: 검색 결과 파일 기반
        parser = argparse.ArgumentParser(
            description='승정원일기 크롤링 - A모드 (검색 결과 기반)',
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="""
Examples:
  # A모드: 검색 결과 기반 크롤링
  python sjw_crawler.py /tmp/sjw_results.json --name 송시열_승정원
  python sjw_crawler.py results.json --name 산림_현종 --workers 6
  python sjw_crawler.py results.json --name 산림_현종 --resume

  # B모드: 날짜 범위 열람
  python sjw_crawler.py browse --reign 현종 --name 현종_전체
  python sjw_crawler.py browse --reign 숙종 --year-from 20 --year-to 25 --name 숙종_20_25년
            """
        )
        parser.add_argument('input_file', help='입력 파일 (JSON)')
        parser.add_argument('--name', '-n', required=True, help='컬렉션 이름')
        parser.add_argument('--workers', '-w', type=int, default=4, help='병렬 워커 수 (기본: 4)')
        parser.add_argument('--resume', '-r', action='store_true', help='중단된 작업 재개')
        parser.add_argument('--limit', '-l', type=int, help='수집 건수 제한 (테스트용)')

        args = parser.parse_args()

        crawl_mode = "search"
        try:
            with open(args.input_file, 'r', encoding='utf-8') as f:
                input_data = json.load(f)
                if 'metadata' in input_data and 'keywords' in input_data['metadata']:
                    search_keywords = input_data['metadata']['keywords']
        except:
            pass

        print(f"A모드: {args.input_file} 기반 크롤링")
        entries = parse_input_file(args.input_file)
        print(f"  Found {len(entries)} entries")

    if not entries:
        print("No entries found")
        sys.exit(1)

    # 제한 적용
    if args.limit:
        entries = entries[:args.limit]
        print(f"  Limited to {len(entries)} entries")

    # 크롤링 실행
    output_dir = crawl_articles(
        entries,
        args.name,
        num_workers=args.workers,
        resume=args.resume
    )

    print(f"\nDone! Collection saved to: {output_dir}")
    print(f'\n다음 단계: 전처리 (요약 + 인덱싱) 진행')
    print(f'  Claude에게 "DB/SJW/{args.name} 전처리해줘" 라고 요청하세요.')


if __name__ == '__main__':
    main()
