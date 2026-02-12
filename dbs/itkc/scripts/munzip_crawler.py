#!/usr/bin/env python3
"""
한국고전종합DB 문집 크롤러 (itkc_crawler.py)
한국문집총간(MO) 기사를 수집하여 JSON으로 저장

Usage:
    # 검색 결과 크롤링
    python itkc_crawler.py search --query "正人心" --collection ITKC_MO_0367A --name 송자대전_정인심

    # 서명 전체 크롤링
    python itkc_crawler.py full --collection ITKC_MO_0367A --name 송자대전

    # 공통 옵션
    --secId MO_BD        # 검색 대상 (기본: MO_BD 본문검색, full은 MO_GS 사용)
    --workers 4          # 병렬 워커 수
    --resume             # 중단된 작업 재개
    --limit 100          # 수집 건수 제한 (테스트용)

Output:
    DB/Munzip/{collection_name}/
        ├── raw/              # 기사별 개별 JSON
        ├── metadata.json     # 수집 메타정보
        └── failed_articles.json  # 실패 로그 (실패 시)

Note:
    OpenAPI 규격: TOOLS/scripts/reference/itkc_openapi.md
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
from urllib.parse import quote, unquote
import xml.etree.ElementTree as ET

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

DB_PATH = _get_db_root() / "Munzip"

# API 설정
API_BASE = "https://db.itkc.or.kr/openapi/search"
WEB_BASE = "https://db.itkc.or.kr"


def safe_print(*args, **kwargs):
    """스레드 안전 출력"""
    with print_lock:
        print(*args, **kwargs, flush=True)


# =============================================================================
# OpenAPI 호출
# =============================================================================

def fetch_api(params: dict) -> dict:
    """
    OpenAPI 호출 및 XML 파싱

    Returns:
        {
            'total_count': int,
            'articles': [{'자료ID': ..., '기사명': ..., ...}, ...]
        }
    """
    try:
        response = requests.get(API_BASE, params=params, timeout=30)
        response.raise_for_status()

        # XML 파싱
        root = ET.fromstring(response.content)

        # 헤더에서 총 건수
        total_count = 0
        for field in root.findall('.//header/field'):
            if field.get('name') == 'totalCount':
                total_count = int(field.text or 0)
                break

        # 결과 파싱
        articles = []
        for doc in root.findall('.//result/doc'):
            article = {}
            for field in doc.findall('field'):
                name = field.get('name')
                value = field.text or ''
                article[name] = value
            if article.get('자료ID'):
                articles.append(article)

        return {
            'total_count': total_count,
            'articles': articles
        }

    except Exception as e:
        safe_print(f"API 호출 실패: {e}")
        return {'total_count': 0, 'articles': []}


def fetch_article_list_search(collection_id: str, query: str, sec_id: str = 'MO_BD',
                               limit: int = None) -> list:
    """
    검색 결과 기사 목록 수집

    Args:
        collection_id: 서지 ID (예: ITKC_MO_0367A). None이면 전체 검색
        query: 검색어
        sec_id: 검색 대상 (기본: MO_BD)
        limit: 최대 수집 건수
    """
    articles = []
    start = 0
    rows = 100  # 한 번에 100건씩

    # q 파라미터 구성: collection_id가 있으면 opDir 포함, 없으면 전체 검색
    if collection_id:
        q_param = f"query†{query}$opDir†{collection_id}"
    else:
        q_param = f"query†{query}"

    while True:
        params = {
            'secId': sec_id,
            'q': q_param,
            'start': start,
            'rows': rows
        }

        result = fetch_api(params)

        if not result['articles']:
            break

        articles.extend(result['articles'])

        if limit and len(articles) >= limit:
            articles = articles[:limit]
            break

        if len(articles) >= result['total_count']:
            break

        start += rows
        time.sleep(0.3)  # Rate limiting

    return articles


def get_sec_id_for_collection(collection_id: str, search_type: str = 'GS') -> str:
    """
    서지ID에서 카테고리를 추출하여 적절한 secId 반환

    Args:
        collection_id: 서지 ID (예: ITKC_MO_0367A, ITKC_BT_1324A)
        search_type: 검색 유형 (GS=기사명, BD=본문)

    Returns:
        secId (예: MO_GS, BT_GS, GO_GS)
    """
    # ITKC_{카테고리}_{번호} 형식에서 카테고리 추출
    parts = collection_id.split('_')
    if len(parts) >= 2:
        category = parts[1]  # MO, BT, GO, KP 등
        return f"{category}_{search_type}"
    # 기본값: 문집총간
    return f"MO_{search_type}"


def fetch_article_list_full(collection_id: str, limit: int = None) -> list:
    """
    서명 전체 기사 목록 수집

    Args:
        collection_id: 서지 ID (예: ITKC_MO_0367A, ITKC_BT_1324A)
        limit: 최대 수집 건수
    """
    articles = []
    start = 0
    rows = 100

    # 서지ID에서 카테고리 추출하여 secId 결정
    sec_id = get_sec_id_for_collection(collection_id, 'GS')
    safe_print(f"사용 secId: {sec_id}")

    # 기사명 검색으로 전체 목록 (검색어 없이 opDir만)
    q_param = f"opDir†{collection_id}"

    while True:
        params = {
            'secId': sec_id,  # 동적으로 결정된 secId
            'q': q_param,
            'start': start,
            'rows': rows
        }

        result = fetch_api(params)

        if start == 0:
            safe_print(f"총 {result['total_count']}건 발견")

        if not result['articles']:
            break

        articles.extend(result['articles'])

        if limit and len(articles) >= limit:
            articles = articles[:limit]
            break

        if len(articles) >= result['total_count']:
            break

        start += rows

        if start % 500 == 0:
            safe_print(f"  목록 수집 중... {len(articles)}건")

        time.sleep(0.3)

    return articles


# =============================================================================
# 기사 내용 크롤링
# =============================================================================

def clean_text(text: str) -> str:
    """텍스트 정리"""
    if not text:
        return ''

    # HTML 태그 제거
    text = re.sub(r'<[^>]+>', '', text)
    # 연속 공백 정리
    text = re.sub(r'\s+', ' ', text)
    # 앞뒤 공백 제거
    text = text.strip()

    return text


def extract_paragraphs(soup, selector: str) -> str:
    """특정 셀렉터 내의 문단들을 추출"""
    container = soup.select_one(selector)
    if not container:
        return ''

    paragraphs = []
    for para in container.select('div.xsl_para, div.xsl_para_tit'):
        text = clean_text(para.get_text())
        if text:
            paragraphs.append(text)

    return '\n\n'.join(paragraphs)


def is_bt_collection(data_id: str) -> bool:
    """BT(고전번역서) 카테고리인지 확인"""
    return '_BT_' in data_id


def fetch_article_content(data_id: str, retry: int = 3) -> dict:
    """
    기사 페이지에서 원문/번역문 추출

    Args:
        data_id: 자료ID (예: ITKC_MO_0367A_0070_010_0020, ITKC_BT_1324A_0010_000_0010)
        retry: 재시도 횟수

    Returns:
        {
            'title': str,
            'title_ko': str,
            'original': str,
            'translation': str,
            'has_translation': bool
        }
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
    }

    is_bt = is_bt_collection(data_id)

    for attempt in range(retry):
        try:
            result = {
                'title': '',
                'title_ko': '',
                'original': '',
                'translation': '',
                'has_translation': False
            }

            if is_bt:
                # BT(고전번역서): 기본 페이지가 번역문, 원문은 viewSync=ORI로 별도 요청
                # 1. 번역문 페이지 요청 (기본)
                url_trans = f"{WEB_BASE}/dir/node?dataId={data_id}"
                response = requests.get(url_trans, headers=headers, timeout=30)
                response.raise_for_status()
                soup_trans = BeautifulSoup(response.text, 'html.parser')

                # 번역문 제목 추출
                title_elem = soup_trans.select_one('div.text_body_tit h4')
                if title_elem:
                    result['title_ko'] = clean_text(title_elem.get_text())

                # 번역문 추출 (BT는 div.text_body에 바로 있음)
                translation = extract_paragraphs(soup_trans, 'div.text_body')
                if translation:
                    result['translation'] = translation
                    result['has_translation'] = True

                # 2. 원문 페이지 요청
                url_ori = f"{WEB_BASE}/dir/node?dataId={data_id}&viewSync=ORI"
                response_ori = requests.get(url_ori, headers=headers, timeout=30)
                if response_ori.status_code == 200:
                    soup_ori = BeautifulSoup(response_ori.text, 'html.parser')

                    # 원문 제목
                    ori_title = soup_ori.select_one('div.text_body_tit h4')
                    if ori_title:
                        result['title'] = clean_text(ori_title.get_text())

                    # 원문 추출
                    original = extract_paragraphs(soup_ori, 'div.text_body')
                    if original:
                        result['original'] = original

            else:
                # MO(문집총간) 등: 기존 로직
                url = f"{WEB_BASE}/dir/node?dataId={data_id}&viewSync=TR"
                response = requests.get(url, headers=headers, timeout=30)
                response.raise_for_status()

                soup = BeautifulSoup(response.text, 'html.parser')

                # 원문 제목 추출
                title_elem = soup.select_one('div.text_body_tit.ori h4')
                if title_elem:
                    result['title'] = clean_text(title_elem.get_text())

                # 원문 추출 (div.text_body.ori 또는 gisa1 내부)
                original_selectors = [
                    'div.text_body.ori',
                    'div.gisa1 div.text_body',
                    'div.w50.gisa-wrap.gisa1 div.text_body'
                ]
                for selector in original_selectors:
                    original = extract_paragraphs(soup, selector)
                    if original:
                        result['original'] = original
                        break

                # 번역문 추출 (gisa2 내부)
                translation_selectors = [
                    'div.gisa2 div.text_body',
                    'div.w50.gisa-wrap.gisa2 div.text_body'
                ]
                for selector in translation_selectors:
                    translation = extract_paragraphs(soup, selector)
                    if translation:
                        result['translation'] = translation
                        result['has_translation'] = True
                        break

                # 번역문 제목 (있는 경우)
                if result['has_translation']:
                    trans_title = soup.select_one('div.gisa2 div.text_body_tit h4')
                    if trans_title:
                        result['title_ko'] = clean_text(trans_title.get_text())

            return result

        except Exception as e:
            if attempt < retry - 1:
                time.sleep(2 * (attempt + 1))
            else:
                return {
                    'title': '',
                    'title_ko': '',
                    'original': '[크롤링 실패]',
                    'translation': '',
                    'has_translation': False,
                    'error': str(e)
                }

    return {
        'title': '',
        'title_ko': '',
        'original': '[크롤링 실패]',
        'translation': '',
        'has_translation': False
    }


def parse_author(author_str: str) -> dict:
    """저자 문자열 파싱 (한글|한자 형식)"""
    if not author_str:
        return {'name': '', 'name_hanja': ''}

    if '|' in author_str:
        parts = author_str.split('|')
        return {
            'name': parts[0].strip(),
            'name_hanja': parts[1].strip() if len(parts) > 1 else ''
        }
    return {'name': author_str, 'name_hanja': ''}


def parse_seo_myeong(seo_myeong: str) -> dict:
    """서명 파싱 (한글(한자) 형식)"""
    if not seo_myeong:
        return {'name': '', 'name_hanja': ''}

    match = re.match(r'^(.+?)\((.+)\)$', seo_myeong)
    if match:
        return {
            'name': match.group(1).strip(),
            'name_hanja': match.group(2).strip()
        }
    return {'name': seo_myeong, 'name_hanja': ''}


def fetch_article_with_content(api_article: dict) -> dict:
    """API 결과 + 내용 크롤링 통합"""
    global processed_count, total_count

    data_id = api_article.get('자료ID', '')

    try:
        content = fetch_article_content(data_id)

        with progress_lock:
            processed_count += 1
            current = processed_count

        title_display = api_article.get('기사명', '')[:40]
        trans_mark = '✓' if content.get('has_translation') else '✗'
        safe_print(f"[{current}/{total_count}] {trans_mark} {title_display}...")

        # 저자 파싱
        author = parse_author(api_article.get('저자', ''))
        author['birth_year'] = int(api_article.get('저자생년', 0) or 0)
        author['death_year'] = int(api_article.get('저자몰년', 0) or 0)

        # 서명 파싱
        seo_myeong = parse_seo_myeong(api_article.get('서명', ''))

        article = {
            'id': data_id,
            'title': content.get('title') or api_article.get('기사명', ''),
            'date': {
                'reign': None,
                'year': None,
                'month': None,
                'day': None
            },
            'source': {
                'seo_myeong': seo_myeong.get('name', ''),
                'seo_myeong_hanja': seo_myeong.get('name_hanja', ''),
                'gwon_cha': api_article.get('권차명', ''),
                'mun_che': api_article.get('문체명', '')
            },
            'source_specific': {
                'title_ko': content.get('title_ko', ''),
                'author': author,
                'dci': api_article.get('DCI_s', ''),
                'jibsu': api_article.get('집수번호', ''),
                'mun_che_category': api_article.get('문체분류', '')
            },
            'url': f"{WEB_BASE}/dir/item?itemId={data_id.split('_')[1] if '_' in data_id else 'MO'}#/dir/node?dataId={data_id}",
            'original': content.get('original', ''),
            'translation': content.get('translation', ''),
            'has_translation': content.get('has_translation', False)
        }

        return {
            'article': article,
            'success': True
        }

    except Exception as e:
        safe_print(f"Error: {data_id} - {e}")
        return {
            'article': None,
            'success': False,
            'error': {
                'id': data_id,
                'title': api_article.get('기사명', ''),
                'error_type': type(e).__name__,
                'error_message': str(e),
                'timestamp': datetime.now().isoformat()
            }
        }


# =============================================================================
# 메인 크롤링 로직
# =============================================================================

def crawl_articles(api_articles: list, collection_name: str, num_workers: int = 4,
                   resume: bool = False, crawl_mode: str = None, search_params: dict = None):
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
            print(f"Resuming: {len(completed_ids)} entries already completed")

    # 남은 작업 필터링
    remaining = [a for a in api_articles if a.get('자료ID') not in completed_ids]
    total_count = len(remaining)
    processed_count = 0

    print(f"\nProcessing {len(remaining)} entries with {num_workers} workers...")
    print(f"(✓=번역문 있음, ✗=원문만)")

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
            futures = {executor.submit(fetch_article_with_content, a): a for a in remaining}

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

                # Rate limiting
                time.sleep(0.3)

    # 최종 저장
    # ID 순 정렬
    articles.sort(key=lambda a: a['id'])

    # 번역문 통계
    trans_count = sum(1 for a in articles if a.get('has_translation'))

    # metadata.json 저장
    seo_myeong_set = set()
    for a in articles:
        if a.get('source', {}).get('seo_myeong'):
            seo_myeong_set.add(a['source']['seo_myeong'])

    metadata = {
        'collection_name': collection_name,
        'crawl_date': datetime.now().isoformat(),
        'total_articles': len(articles),
        'articles_with_translation': trans_count,
        'source': 'munzip',
        'source_detail': list(seo_myeong_set),
        'crawl_mode': crawl_mode or 'unknown',
        'search_params': search_params or {},
        'date_range': {
            'start': None,
            'end': None
        }
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
    print(f"  - 번역문 포함: {trans_count}/{len(articles)}건 ({trans_count*100//len(articles) if articles else 0}%)")
    if failed_articles:
        print(f"  - failed_articles.json: 실패 로그 ({len(failed_articles)}건)")

    return output_dir


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='한국고전종합DB 문집 크롤러',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # 검색 결과 크롤링
  python itkc_crawler.py search --query "正人心" --collection ITKC_MO_0367A --name 송자대전_정인심

  # 서명 전체 크롤링
  python itkc_crawler.py full --collection ITKC_MO_0367A --name 송자대전

  # 테스트 (5건만)
  python itkc_crawler.py search --query "正人心" --collection ITKC_MO_0367A --name test --limit 5
        """
    )

    subparsers = parser.add_subparsers(dest='mode', help='크롤링 모드')

    # search 모드
    search_parser = subparsers.add_parser('search', help='검색 결과 크롤링')
    search_parser.add_argument('-q', '--query', required=True, help='검색어')
    search_parser.add_argument('-c', '--collection', help='서지 ID (예: ITKC_MO_0367A). 생략시 전체 검색')
    search_parser.add_argument('-n', '--name', required=True, help='컬렉션 이름 (출력 폴더명)')
    search_parser.add_argument('--secId', default='MO_BD', help='검색 대상 (기본: MO_BD)')
    search_parser.add_argument('-w', '--workers', type=int, default=4, help='병렬 워커 수')
    search_parser.add_argument('-r', '--resume', action='store_true', help='중단된 작업 재개')
    search_parser.add_argument('-l', '--limit', type=int, help='수집 건수 제한')
    search_parser.add_argument('--count-only', action='store_true', help='결과 수만 확인 (크롤링 안 함)')

    # full 모드
    full_parser = subparsers.add_parser('full', help='서명 전체 크롤링')
    full_parser.add_argument('-c', '--collection', required=True, help='서지 ID (예: ITKC_MO_0367A)')
    full_parser.add_argument('-n', '--name', required=True, help='컬렉션 이름 (출력 폴더명)')
    full_parser.add_argument('-w', '--workers', type=int, default=4, help='병렬 워커 수')
    full_parser.add_argument('-r', '--resume', action='store_true', help='중단된 작업 재개')
    full_parser.add_argument('-l', '--limit', type=int, help='수집 건수 제한')
    full_parser.add_argument('--count-only', action='store_true', help='결과 수만 확인 (크롤링 안 함)')

    args = parser.parse_args()

    if not args.mode:
        parser.print_help()
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"한국고전종합DB 문집 크롤러")
    print(f"{'='*60}")
    print(f"모드: {args.mode}")
    if args.mode == 'search':
        if args.collection:
            print(f"서지 ID: {args.collection}")
        else:
            print(f"검색 범위: 한국문집총간 전체")
        print(f"검색어: {args.query}")
    else:
        print(f"서지 ID: {args.collection}")
    print(f"컬렉션명: {args.name}")
    if args.limit:
        print(f"제한: {args.limit}건")
    print()

    # count-only 모드: API 1회 호출로 건수만 확인
    if args.count_only:
        print("검색 결과 수 확인 중...")
        if args.mode == 'search':
            sec_id = args.secId
            if args.collection and sec_id == 'MO_BD':
                sec_id = get_sec_id_for_collection(args.collection, 'BD')
            if args.collection:
                q_param = f"query†{args.query}$opDir†{args.collection}"
            else:
                q_param = f"query†{args.query}"
            result = fetch_api({'secId': sec_id, 'q': q_param, 'start': 0, 'rows': 1})
        else:  # full
            sec_id = get_sec_id_for_collection(args.collection, 'GS')
            q_param = f"opDir†{args.collection}"
            result = fetch_api({'secId': sec_id, 'q': q_param, 'start': 0, 'rows': 1})

        print(f"총 {result['total_count']}건")
        sys.exit(0)

    # 기사 목록 수집
    print("기사 목록 수집 중...")

    if args.mode == 'search':
        # collection이 주어지고 secId가 기본값이면 자동 감지
        sec_id = args.secId
        if args.collection and sec_id == 'MO_BD':
            sec_id = get_sec_id_for_collection(args.collection, 'BD')
        api_articles = fetch_article_list_search(
            args.collection,
            args.query,
            sec_id,
            args.limit
        )
    else:  # full
        api_articles = fetch_article_list_full(
            args.collection,
            args.limit
        )

    if not api_articles:
        print("수집된 기사가 없습니다.")
        sys.exit(1)

    print(f"총 {len(api_articles)}건 기사 발견\n")

    # 크롤링 실행
    search_params = {'keywords': [args.query]} if args.mode == 'search' and hasattr(args, 'query') else {}
    output_dir = crawl_articles(
        api_articles,
        args.name,
        num_workers=args.workers,
        resume=args.resume,
        crawl_mode=args.mode,
        search_params=search_params
    )

    print(f"\n{'='*60}")
    print(f"완료! Collection saved to: {output_dir}")
    print(f"{'='*60}")


if __name__ == '__main__':
    main()
