#!/usr/bin/env python3
"""
실록 크롤링 스크립트 (sillok_crawler.py)
조선왕조실록 사이트에서 기사를 수집하여 JSON으로 저장

Usage:
    python sillok_crawler.py <input.txt> --name <collection_name>

Examples:
    python sillok_crawler.py ~/Downloads/실록_효종실록.txt --name 송시열_효종실록
    python sillok_crawler.py urls.txt --name 산림_숙종실록 --workers 6

Input file format (TSV with ^ delimiter, from 실록 사이트 검색 결과 다운로드):
    기사 ID^권수^날짜^제목^기사 URL

Output:
    DB/Sillok/{collection_name}/
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

DB_PATH = _get_db_root() / "Sillok"

# HTTP 세션 설정
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


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


def parse_input_file(filepath: str, input_format: str = 'auto') -> list[dict]:
    """
    입력 파일 파싱 (TSV 또는 JSON)

    Args:
        filepath: 입력 파일 경로
        input_format: 'auto', 'tsv', 'json' 중 하나

    Returns:
        기사 목록
    """
    # 포맷 자동 감지
    if input_format == 'auto':
        if filepath.endswith('.json'):
            input_format = 'json'
        else:
            input_format = 'tsv'

    if input_format == 'json':
        return parse_json_input(filepath)
    else:
        return parse_tsv_input(filepath)


def parse_json_input(filepath: str) -> list[dict]:
    """JSON 입력 파일 파싱 (sillok_search.py 출력 형식)"""
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # sillok_search.py 출력 형식: {'metadata': {...}, 'entries': [...]}
    if 'entries' in data:
        raw_entries = data['entries']
    elif isinstance(data, list):
        raw_entries = data
    else:
        raw_entries = []

    entries = []
    for item in raw_entries:
        # 날짜 정보 파싱
        date_str = item.get('date', '')
        date_info = parse_date_info(date_str)

        entry = {
            'id': item.get('id', ''),
            'volume_info': item.get('volume', ''),
            'date_str': date_str,
            'date': date_info,
            'title': item.get('title', ''),
            'url': item.get('url', '')
        }
        entries.append(entry)

    return entries


def parse_tsv_input(filepath: str) -> list[dict]:
    """TSV 입력 파일 파싱 (^ 구분자)"""
    entries = []
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    # 헤더 스킵
    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue

        parts = line.split('^')
        if len(parts) >= 5:
            # 날짜 정보 파싱
            date_info = parse_date_info(parts[2])

            entry = {
                'id': parts[0],
                'volume_info': parts[1],  # 예: "효종실록 5권"
                'date_str': parts[2],     # 원본 날짜 문자열
                'date': date_info,
                'title': parts[3],
                'url': parts[4]
            }
            entries.append(entry)

    return entries


def parse_date_info(date_str: str) -> dict:
    """
    날짜 문자열 파싱

    Examples:
        "효종 1년 2월 3일 甲申 1번째기사" → 중국어 간지, N번째 형식
        "현종 즉위년 5월 4일 갑자 2/7 기사" → 한국어 간지, N/M 형식
    """
    result = {
        'reign': '',
        'year': 0,
        'month': 0,
        'day': 0,
        'ganzhi': '',
        'article_num': 1
    }

    # 왕대 추출
    reign_match = re.match(r'^(\S+)\s+', date_str)
    if reign_match:
        result['reign'] = reign_match.group(1)

    # 연월일 추출 (즉위년 = 0년)
    year_match = re.search(r'(\d+)년', date_str)
    month_match = re.search(r'(\d+)월', date_str)
    day_match = re.search(r'(\d+)일', date_str)

    if year_match:
        result['year'] = int(year_match.group(1))
    # 즉위년은 year=0으로 유지 (기본값)
    if month_match:
        result['month'] = int(month_match.group(1))
    if day_match:
        result['day'] = int(day_match.group(1))

    # 간지 추출 (중국어 + 한국어 모두 지원)
    ganzhi_pattern = r'[甲乙丙丁戊己庚辛壬癸갑을병정무기경신임계][子丑寅卯辰巳午未申酉戌亥자축인묘진사오미신유술해]'
    ganzhi_match = re.search(ganzhi_pattern, date_str)
    if ganzhi_match:
        result['ganzhi'] = ganzhi_match.group(0)

    # 기사 번호 추출
    num_match = re.search(r'(\d+)번째', date_str)
    if num_match:
        result['article_num'] = int(num_match.group(1))
    else:
        fraction_match = re.search(r'(\d+)/\d+\s*기사', date_str)
        if fraction_match:
            result['article_num'] = int(fraction_match.group(1))

    return result


def parse_volume_info(volume_str: str) -> dict:
    """
    권수 정보 파싱
    예: "효종실록 5권" → {"sillok": "효종실록", "volume": 5}
    """
    result = {'sillok': '', 'volume': 0, 'page': ''}

    match = re.match(r'^(.+실록|.+보궐정오)\s*(\d+)권?', volume_str)
    if match:
        result['sillok'] = match.group(1).strip()
        result['volume'] = int(match.group(2))
    else:
        result['sillok'] = volume_str

    return result


def extract_footnotes(soup: BeautifulSoup) -> dict:
    """
    ul.ins_footnote에서 주석 추출

    Returns:
        {"017": {"term": "동기(同氣)", "definition": "송시열의 형을 말함."}, ...}
    """
    footnotes = {}
    footnote_list = soup.select_one('ul.ins_footnote')

    if not footnote_list:
        return footnotes

    for item in footnote_list.select('li'):
        link = item.select_one('a')
        if not link:
            continue

        link_text = link.get_text(strip=True)
        marker_match = re.search(r'\[註\s*(\d+)\]', link_text)

        if marker_match:
            marker = marker_match.group(1)
            item_text = item.get_text(strip=True)
            content = re.sub(r'\[註\s*\d+\]\s*', '', item_text)

            if ' : ' in content:
                term, definition = content.split(' : ', 1)
            else:
                term, definition = "", content

            footnotes[marker] = {
                'term': term.strip(),
                'definition': definition.strip()
            }

    return footnotes


def fetch_article(session: requests.Session, url: str, retry: int = 3) -> dict:
    """
    실록 기사 페이지에서 번역문, 원문, 주석, 카테고리 추출 (requests 버전)
    """
    result = {
        'translation': '',
        'original': '',
        'footnotes': {},
        'category': [],
        'page_info': '',
        'title': '',
        'date_info': None
    }

    for attempt in range(retry):
        try:
            response = session.get(url, timeout=30)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')

            # <p class="date"> 요소에서 날짜 정보 추출
            date_elem = soup.select_one('p.date')
            if date_elem:
                date_text = date_elem.get_text(strip=True)
                result['date_info'] = parse_date_info(date_text)

            # 제목 추출 — try known selectors first, then bare <h3> as
            # fallback for IDs-mode article pages where class-based
            # selectors don't match.
            for selector in ['h3.view-tit', '.tit_loc', 'h3.page_tit']:
                title_elem = soup.select_one(selector)
                if title_elem:
                    title_text = title_elem.get_text(strip=True)
                    if title_text:
                        result['title'] = title_text
                        break
            else:
                # IDs-mode fallback: bare <h3> without class, skip
                # known structural headings (content-title, etc.)
                skip_classes = {'content-title'}
                for h3 in soup.select('h3'):
                    h3_classes = set(h3.get('class') or [])
                    if h3_classes & skip_classes:
                        continue
                    if h3_classes:
                        continue
                    h3_text = h3.get_text(strip=True)
                    if h3_text:
                        result['title'] = h3_text
                        break

            # 국역/원문 추출
            for h4 in soup.select('h4.view-title'):
                heading_text = h4.get_text(strip=True)

                if heading_text not in ['국역', '원문']:
                    continue

                parent_div = h4.parent
                if not parent_div:
                    continue

                view_text = parent_div.select_one('div.view-text')
                if not view_text:
                    continue

                paragraphs = view_text.select('p.paragraph')
                texts = []
                for p in paragraphs:
                    p_text = p.get_text(strip=True)
                    if p_text:
                        texts.append(p_text)

                combined_text = '\n\n'.join(texts)

                if heading_text == '국역':
                    result['translation'] = combined_text
                elif heading_text == '원문':
                    result['original'] = combined_text

            # 주석 추출
            result['footnotes'] = extract_footnotes(soup)

            # 카테고리 추출 (【분류】)
            page_source = response.text
            category_section = re.search(r'【분류】(.+?)(?=【|<div|$)', page_source, re.DOTALL)
            if category_section:
                cat_text = category_section.group(1)
                cat_matches = re.findall(r'\[([^\]]+)\]', cat_text)
                for cat in cat_matches:
                    clean_cat = re.sub(r'<[^>]+>', '', cat).strip()
                    if clean_cat and clean_cat not in result['category']:
                        result['category'].append(clean_cat)

            # 출전 정보 추출
            page_info_parts = []
            taebaek_match = re.search(r'【태백산사고본】\s*([^【\n]+)', page_source)
            if taebaek_match:
                info = re.sub(r'<[^>]+>', '', taebaek_match.group(1)).strip()
                if info:
                    page_info_parts.append(f"태백산사고본 {info}")

            gukpyeon_match = re.search(r'【국편영인본】\s*([^【\n]+)', page_source)
            if gukpyeon_match:
                info = re.sub(r'<[^>]+>', '', gukpyeon_match.group(1)).strip()
                if info:
                    page_info_parts.append(f"국편영인본 {info}")

            if page_info_parts:
                result['page_info'] = ' / '.join(page_info_parts)

            return result

        except Exception as e:
            if attempt < retry - 1:
                time.sleep(1)
            else:
                return {
                    'translation': '[크롤링 실패]',
                    'original': '',
                    'footnotes': {},
                    'category': [],
                    'page_info': '',
                    'title': '',
                    'date_info': None,
                    'error': str(e)
                }

    return result


def fetch_article_task(task: dict) -> dict:
    """워커용: 단일 기사 크롤링"""
    global processed_count, total_count

    session = create_session()

    try:
        url = task['url']
        content = fetch_article(session, url)

        with progress_lock:
            processed_count += 1
            current = processed_count

        title_preview = task['title'][:40] if task['title'] else 'No title'
        safe_print(f"[{current}/{total_count}] Done: {title_preview}...")

        # 결과 조합
        source = parse_volume_info(task['volume_info'])

        # 날짜 정보 병합
        date_info = task['date'].copy()
        if content.get('date_info'):
            page_date = content['date_info']
            if page_date.get('ganzhi'):
                date_info['ganzhi'] = page_date['ganzhi']
            if page_date.get('article_num'):
                date_info['article_num'] = page_date['article_num']

        article = {
            'id': task['id'],
            'title': content['title'] or task['title'],
            'date': date_info,
            'article_num': date_info['article_num'],
            'source': source,
            'url': task['url'],
            'original': content['original'],
            'translation': content['translation'],
            'has_translation': bool(content['translation'].strip()),
            'source_specific': {
                'footnotes': content['footnotes'],
                'page_info': content['page_info'],
                'category': content['category']
            }
        }

        # 크롤링 실패 체크
        if content.get('error') or content['translation'] == '[크롤링 실패]':
            return {
                'article': None,
                'success': False,
                'error': {
                    'id': task['id'],
                    'url': task['url'],
                    'title': task['title'],
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
        safe_print(f"Error fetching {task.get('url', 'unknown')}: {e}")
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


def crawl_articles(entries: list[dict], collection_name: str, num_workers: int = 4, resume: bool = False):
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

    # 최종 저장
    articles.sort(key=lambda a: (
        a['date']['year'],
        a['date']['month'],
        a['date']['day'],
        a['article_num']
    ))

    # metadata.json 저장
    metadata = {
        'collection_name': collection_name,
        'source': 'sillok',
        'crawl_mode': 'file',
        'crawl_date': datetime.now().isoformat(),
        'total_articles': len(articles),
        'articles_with_translation': sum(1 for a in articles if a.get('translation', '').strip()),
        'search_params': {},
        'source_detail': list(set(a['source']['sillok'] for a in articles if a['source']['sillok'])),
        'date_range': {
            'start': f"{articles[0]['date']['reign']} {articles[0]['date']['year']}년" if articles else '',
            'end': f"{articles[-1]['date']['reign']} {articles[-1]['date']['year']}년" if articles else ''
        },
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
    print(f"  - raw/: 기사별 개별 JSON")
    print(f"  - metadata.json: 수집 메타정보")
    if failed_articles:
        print(f"  - failed_articles.json: 실패 로그 ({len(failed_articles)}건)")

    return output_dir


def main():
    parser = argparse.ArgumentParser(description='조선왕조실록 크롤링 스크립트')
    parser.add_argument('input_file', help='입력 파일 (TSV 또는 JSON)')
    parser.add_argument('--name', '-n', required=True, help='컬렉션 이름 (예: 송시열_효종실록)')
    parser.add_argument('--format', '-f', choices=['auto', 'tsv', 'json'], default='auto',
                        help='입력 파일 형식 (기본: auto - 확장자로 판단)')
    parser.add_argument('--workers', '-w', type=int, default=4, help='병렬 워커 수 (기본: 4)')
    parser.add_argument('--resume', '-r', action='store_true', help='중단된 작업 재개')
    parser.add_argument('--preprocess', '-p', action='store_true',
                        help='크롤링 완료 후 자동으로 전처리 에이전트 실행 안내')

    args = parser.parse_args()

    # 입력 파일 파싱
    print(f"Reading {args.input_file}...")
    entries = parse_input_file(args.input_file, input_format=args.format)
    print(f"  Found {len(entries)} entries")

    if not entries:
        print("No entries found in input file")
        sys.exit(1)

    # 크롤링 실행
    output_dir = crawl_articles(
        entries,
        args.name,
        num_workers=args.workers,
        resume=args.resume
    )

    print(f"\nDone! Collection saved to: {output_dir}")

    # 전처리 안내
    if args.preprocess:
        print("\n" + "="*60)
        print("📌 전처리 실행 안내")
        print("="*60)
        print(f"\nClaude에게 다음과 같이 요청하세요:")
        print(f'  "DB/Sillok/{args.name} 전처리해줘"')
        print("="*60)
    else:
        print("\n다음 단계: 전처리 (요약 + 인덱싱) 진행")
        print(f'  Claude에게 "DB/Sillok/{args.name} 전처리해줘" 라고 요청하세요.')


if __name__ == '__main__':
    main()
