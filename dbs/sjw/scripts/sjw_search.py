#!/usr/bin/env python3
"""
승정원일기 검색 스크립트 (sjw_search.py)
승정원일기 사이트에서 키워드 검색 후 결과를 JSON으로 저장

Usage:
    # 기본 검색 (전체 텍스트)
    python sjw_search.py --keywords "宋時烈" --output /tmp/sjw_results.json

    # 복수 키워드 검색 (중복 제거)
    python sjw_search.py --keywords "宋時烈,송시열" --output /tmp/sjw_results.json

    # 인명 필드 검색
    python sjw_search.py --keywords "宋時烈" --field person --output /tmp/sjw_results.json

    # 왕대 범위 지정
    python sjw_search.py --keywords "宋時烈" --reign-from 현종 --reign-to 숙종 --output /tmp/sjw_results.json

    # 결과 수만 확인
    python sjw_search.py --keywords "宋時烈" --count-only

Output:
    JSON 형식 — sjw_crawler.py 입력과 호환

Note:
    - requests 기반 (Selenium 불필요)
    - 페이지당 50건, 모든 페이지 순회
    - 세션 기반 (GET으로 세션 수립 후 POST 검색)
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime

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


# 승정원일기 왕대 순서
REIGN_ORDER = ["인조", "효종", "현종", "숙종", "경종", "영조", "정조", "순조", "헌종", "철종", "고종", "순종"]

# 검색 필드 코드 매핑
FIELD_CODES = {
    'all': 'ALL',
    'person': 'PERSON',
    'place': 'PLACE',
    'book': 'BOOK',
    'seju': 'SEJU',
    'title': 'TITLE',
    'attendance': 'ATTENDANCE',
    'weather': 'WEATHER'
}

SJW_BASE = "https://sjw.history.go.kr"
SEARCH_URL = f"{SJW_BASE}/search/searchResultList.do"
SESSION_URL = f"{SJW_BASE}/search/detailSearch.do"


class SjwSearcher:
    """승정원일기 검색 - requests 기반"""

    ITEMS_PER_PAGE = 50

    def __init__(self):
        self.session = None

    def setup_session(self):
        """HTTP 세션 설정 (GET으로 JSESSIONID 확보)"""
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
        })
        # 세션 수립
        self.session.get(SESSION_URL, timeout=30)

    def close(self):
        """세션 종료"""
        if self.session:
            self.session.close()
            self.session = None

    def _build_simple_data(self, keyword: str, king_name: str = 'ALL',
                           page: int = 0) -> dict:
        """일반 검색 POST 데이터 생성"""
        data = {
            'searchTerm': keyword,
            'searchTermImages': keyword,
            'detailInfo': 'N',
            'kingName': king_name,
            'orderField': 'AGE_SORT',
            'treeType': '왕대별',
        }
        if page > 0:
            data.update({
                'currentPageNo': str(page),
                'recordCountPerPage': '50',
                'pageSize': '10',
                'searchRule': keyword,
                'persons': '',
                'searchQuery': '',
                'searchQueryHTML': '',
                'searchNavigation': '',
                'searchNavigationImages': '',
            })
        return data

    def _build_detail_data(self, keyword: str, field: str = 'ALL',
                           page: int = 0) -> dict:
        """상세 검색 POST 데이터 생성"""
        field_code = FIELD_CODES.get(field, 'ALL')
        search_query = f"{keyword}\u24d0\u24d1\u24d2{field_code}\u24d0\u24d1\u24d2AND"

        data = {
            'searchQuery': search_query,
            'searchQueryHTML': search_query,
            'detailInfo': 'Y',
            'synType': '',
            'transType': '',
            'orderField': 'AGE_SORT',
            'treeType': '왕대별',
        }
        if page > 0:
            data.update({
                'currentPageNo': str(page),
                'recordCountPerPage': '50',
                'pageSize': '10',
                'searchRule': keyword,
                'searchTerm': '',
                'searchTermImages': '',
                'persons': '',
                'kingName': 'ALL',
                'searchNavigation': '',
                'searchNavigationImages': '',
            })
        return data

    def _parse_total_count(self, soup: BeautifulSoup) -> int:
        """검색 결과 총 건수 추출"""
        result_text = soup.select_one('.result-text')
        if result_text:
            match = re.search(r'<strong>([\d,]+)</strong>\s*건', str(result_text))
            if match:
                return int(match.group(1).replace(',', ''))
        return 0

    def _parse_reign_counts(self, soup: BeautifulSoup) -> dict:
        """왕대별 검색 결과 수 추출"""
        counts = {}
        for item in soup.select('.cate-item'):
            text = item.get_text(strip=True)
            match = re.match(r'(.+?)\s*\(([\d,]+)\)', text)
            if match:
                name = match.group(1)
                count = int(match.group(2).replace(',', ''))
                if name != '전체':
                    counts[name] = count
        return counts

    def _parse_entries(self, soup: BeautifulSoup) -> list:
        """검색 결과 페이지에서 기사 목록 추출"""
        entries = []
        for elem in soup.select('[id^="SJW_ANC_"]'):
            article_id = elem.get('id', '').replace('SJW_ANC_', '')
            if not article_id:
                continue

            full_text = elem.get_text(strip=True)

            # "1. 인조 14년 12월 11일  신사 1636년 / 제목" 패턴
            # 변형: "즉위년", "윤4월", 간지 없는 경우(0일) 등
            match = re.match(
                r'\d+\.\s*(.+?)\s+(\d+|즉위)년\s+(윤?)(\d+)월\s+(\d+)일\s+(?:(\S+)\s+)?(\d+)년\s*/\s*(.+)',
                full_text
            )
            if match:
                reign = match.group(1)
                year = 0 if match.group(2) == '즉위' else int(match.group(2))
                is_leap = match.group(3) == '윤'
                month = int(match.group(4))
                day = int(match.group(5))
                ganzhi = match.group(6) or ''
                western_year = int(match.group(7))
                title = match.group(8).strip()

                month_str = f"윤{month}" if is_leap else str(month)
                entries.append({
                    'id': article_id,
                    'date': f"{reign} {year}년 {month_str}월 {day}일",
                    'title': title,
                    'url': f"{SJW_BASE}/id/{article_id}",
                    'reign': reign,
                    'year': year,
                    'month': month,
                    'day': day,
                    'is_leap_month': is_leap,
                    'ganzhi': ganzhi,
                    'western_year': western_year
                })
            else:
                # 패턴 불일치 시 최소 정보로 추가
                entries.append({
                    'id': article_id,
                    'date': full_text.split('/')[0].strip() if '/' in full_text else '',
                    'title': full_text.split('/')[-1].strip() if '/' in full_text else full_text,
                    'url': f"{SJW_BASE}/id/{article_id}",
                    'reign': '',
                    'year': 0,
                    'month': 0,
                    'day': 0,
                    'ganzhi': '',
                    'western_year': 0
                })

        return entries

    def search(self, keyword: str, field: str = 'all',
               king_name: str = 'ALL') -> tuple:
        """
        검색 실행 (첫 페이지)

        Returns:
            (total_count, first_page_entries, reign_counts)
        """
        if field == 'all' and king_name != 'ALL':
            # 일반 검색 + 왕대 필터
            data = self._build_simple_data(keyword, king_name=king_name)
        elif field != 'all':
            # 상세 검색 (필드 지정)
            data = self._build_detail_data(keyword, field=field)
        else:
            # 일반 검색
            data = self._build_simple_data(keyword)

        resp = self.session.post(SEARCH_URL, data=data, timeout=30)
        soup = BeautifulSoup(resp.text, 'html.parser')

        total_count = self._parse_total_count(soup)
        entries = self._parse_entries(soup)
        reign_counts = self._parse_reign_counts(soup)

        return total_count, entries, reign_counts

    def fetch_page(self, keyword: str, page: int, field: str = 'all',
                   king_name: str = 'ALL') -> list:
        """특정 페이지 결과 수집"""
        if field == 'all':
            data = self._build_simple_data(keyword, king_name=king_name, page=page)
        else:
            data = self._build_detail_data(keyword, field=field, page=page)

        resp = self.session.post(SEARCH_URL, data=data, timeout=30)
        soup = BeautifulSoup(resp.text, 'html.parser')
        return self._parse_entries(soup)

    def search_and_collect(self, keyword: str, field: str = 'all',
                           king_name: str = 'ALL',
                           limit: int | None = None) -> dict:
        """
        키워드 검색 후 모든 페이지에서 결과 수집

        Returns:
            {'total_count': N, 'entries': [...], 'reign_counts': {...}}
        """
        print(f"검색 중: {keyword}", end='')
        if field != 'all':
            print(f" (필드: {field})", end='')
        if king_name != 'ALL':
            print(f" (왕대: {king_name})", end='')
        print()

        total_count, first_entries, reign_counts = self.search(
            keyword, field=field, king_name=king_name
        )
        print(f"  → {total_count:,}건 발견")

        if total_count == 0:
            return {'total_count': 0, 'entries': [], 'reign_counts': {}}

        all_entries = list(first_entries)
        if limit and len(all_entries) >= limit:
            all_entries = all_entries[:limit]
            print(f"  → early limit 적용: {len(all_entries)}건")
            return {
                'total_count': total_count,
                'entries': all_entries,
                'reign_counts': reign_counts
            }

        total_pages = (total_count + self.ITEMS_PER_PAGE - 1) // self.ITEMS_PER_PAGE

        if total_pages > 1:
            print(f"  총 {total_pages} 페이지 수집 중...")

        for page in range(2, total_pages + 1):
            entries = self.fetch_page(keyword, page, field=field,
                                      king_name=king_name)
            all_entries.extend(entries)

            if limit and len(all_entries) >= limit:
                all_entries = all_entries[:limit]
                print(f"  → early limit 적용: {len(all_entries)}건 (page {page}/{total_pages})")
                break

            if page % 10 == 0 or page == total_pages:
                print(f"    [{page}/{total_pages}] 수집: {len(all_entries)}건")

            time.sleep(0.3)

        print(f"  → 수집 완료: {len(all_entries)}건")
        return {
            'total_count': total_count,
            'entries': all_entries,
            'reign_counts': reign_counts
        }


def filter_by_reign_range(entries: list, reign_from: str, reign_to: str) -> list:
    """왕대 범위로 필터링"""
    if not reign_from and not reign_to:
        return entries

    try:
        from_idx = REIGN_ORDER.index(reign_from) if reign_from else 0
        to_idx = REIGN_ORDER.index(reign_to) if reign_to else len(REIGN_ORDER) - 1
    except ValueError as e:
        print(f"경고: 유효하지 않은 왕대명 - {e}")
        return entries

    allowed = set(REIGN_ORDER[from_idx:to_idx + 1])
    return [e for e in entries if e.get('reign') in allowed]


def save_json(entries: list, output_path: str, metadata: dict):
    """JSON 형식으로 저장 (sjw_crawler.py 호환)"""
    data = {
        'metadata': metadata,
        'entries': entries
    }
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser(
        description='승정원일기 검색 스크립트',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # 기본 검색
  python sjw_search.py -k "宋時烈" -o /tmp/sjw_results.json

  # 복수 키워드 (중복 제거)
  python sjw_search.py -k "宋時烈,송시열" -o /tmp/sjw_results.json

  # 인명 필드 검색
  python sjw_search.py -k "宋時烈" -f person -o /tmp/sjw_results.json

  # 왕대 범위 지정
  python sjw_search.py -k "宋時烈" -rf 현종 -rt 숙종 -o /tmp/sjw_results.json

  # 결과 수만 확인
  python sjw_search.py -k "宋時烈" -c

Fields: all, person, place, book, seju, title, attendance, weather
        """
    )

    parser.add_argument('--keywords', '-k', required=True,
                        help='검색 키워드 (쉼표로 구분)')
    parser.add_argument('--output', '-o',
                        help='출력 파일 경로 (JSON)')
    parser.add_argument('--field', '-f', choices=list(FIELD_CODES.keys()),
                        default='all', help='검색 필드 (기본: all)')
    parser.add_argument('--reign-from', '-rf',
                        help='시작 왕대 (예: 현종)')
    parser.add_argument('--reign-to', '-rt',
                        help='종료 왕대 (예: 숙종)')
    parser.add_argument('--count-only', '-c', action='store_true',
                        help='결과 수만 확인')

    args = parser.parse_args()

    keywords = [k.strip() for k in args.keywords.split(',') if k.strip()]
    if not keywords:
        print("키워드를 입력해주세요.")
        sys.exit(1)

    if not args.count_only and not args.output:
        print("출력 파일 경로를 지정해주세요. (--output)")
        sys.exit(1)

    # 왕대 필터: 서버 필터 (단일 왕대) vs 클라이언트 필터 (범위)
    # 서버 필터는 단일 왕대만 지원하므로, 범위 필터는 클라이언트에서 처리
    reign_from = args.reign_from
    reign_to = args.reign_to
    server_king = 'ALL'
    client_filter = False

    if reign_from and reign_to and reign_from == reign_to:
        # 단일 왕대 → 서버에서 필터링
        server_king = reign_from
    elif reign_from or reign_to:
        # 범위 → 클라이언트에서 필터링
        client_filter = True

    print(f"검색 키워드: {keywords}")
    if args.field != 'all':
        print(f"검색 필드: {args.field}")
    if reign_from or reign_to:
        print(f"왕대 범위: {reign_from or '인조'}~{reign_to or '순종'}")
    if not args.count_only:
        print(f"출력 파일: {args.output}")
    print()

    searcher = SjwSearcher()

    try:
        searcher.setup_session()

        if args.count_only:
            for keyword in keywords:
                total, _, reign_counts = searcher.search(
                    keyword, field=args.field, king_name=server_king
                )
                print(f"  '{keyword}' → {total:,}건")
                if reign_counts:
                    for reign, count in reign_counts.items():
                        print(f"    {reign}: {count:,}건")
        else:
            all_entries = []
            seen_ids = set()
            keyword_stats = {}

            for keyword in keywords:
                result = searcher.search_and_collect(
                    keyword, field=args.field, king_name=server_king
                )
                keyword_stats[keyword] = result['total_count']

                for entry in result['entries']:
                    if entry['id'] not in seen_ids:
                        seen_ids.add(entry['id'])
                        all_entries.append(entry)

                if keyword != keywords[-1]:
                    time.sleep(1)

            # 왕대 범위 필터링
            if client_filter:
                before = len(all_entries)
                all_entries = filter_by_reign_range(all_entries, reign_from, reign_to)
                print(f"\n왕대 필터링: {before:,}건 → {len(all_entries):,}건")

            # 메타데이터
            metadata = {
                'keywords': ','.join(keywords),
                'field': args.field,
                'total_count': len(all_entries),
                'keyword_stats': keyword_stats,
                'search_date': datetime.now().isoformat(),
                'source': '승정원일기'
            }
            if reign_from or reign_to:
                metadata['reign_range'] = f"{reign_from or '인조'}~{reign_to or '순종'}"

            save_json(all_entries, args.output, metadata)

            print(f"\n{'='*50}")
            print(f"검색 완료: {len(all_entries):,}건")
            print(f"저장: {args.output}")
            print(f"\n다음 단계: 크롤링")
            print(f"  python sjw_crawler.py {args.output} --name <컬렉션명>")

    finally:
        searcher.close()


if __name__ == '__main__':
    main()
