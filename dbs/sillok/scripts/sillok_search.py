#!/usr/bin/env python3
"""
실록 검색 스크립트 (sillok_search.py)
조선왕조실록 사이트에서 키워드 검색 후 결과를 TSV/JSON으로 저장

Usage:
    # 단일 키워드 검색 (기본: 원문 탭)
    python sillok_search.py --keywords "송시열" --output results.tsv

    # 복수 키워드 검색 (각 키워드 결과 병합, 중복 제거)
    python sillok_search.py --keywords "광기,狂氣,발광,發狂" --output results.tsv

    # 국역 탭에서 검색 (한글 키워드)
    python sillok_search.py --keywords "송시열" --tab k --output results.tsv

    # JSON 형식 출력
    python sillok_search.py --keywords "탕평" --output results.json --format json

    # 검색 결과 수만 확인 (다운로드 없이)
    python sillok_search.py --keywords "송시열" --count-only

Output:
    TSV: 기존 sillok_crawler.py 입력 형식과 호환
    JSON: 메타데이터 포함 (키워드별 검색 결과 수 등)

Note:
    - requests 기반 (Selenium 불필요)
    - 페이지당 50건, 모든 페이지 순회
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


# 왕대 순서 (필터링용)
REIGN_ORDER = [
    "태조", "정종", "태종", "세종", "문종", "단종", "세조", "예종", "성종",
    "연산군", "중종", "인종", "명종", "선조", "광해군", "인조", "효종",
    "현종", "숙종", "경종", "영조", "정조", "순조", "헌종", "철종", "고종", "순종"
]

# 실록명 → 왕대명 매핑 (실록 사이트 기준)
SILLOK_TO_REIGN = {
    "태조실록": "태조",
    "정종실록": "정종",
    "태종실록": "태종",
    "세종실록": "세종",
    "문종실록": "문종",
    "단종실록": "단종",
    "세조실록": "세조",
    "예종실록": "예종",
    "성종실록": "성종",
    "연산군일기": "연산군",
    "중종실록": "중종",
    "인종실록": "인종",
    "명종실록": "명종",
    "선조실록": "선조",
    "선조수정실록": "선조",
    "광해군일기[중초본]": "광해군",
    "광해군일기[정초본]": "광해군",
    "인조실록": "인조",
    "효종실록": "효종",
    "현종실록": "현종",
    "현종개수실록": "현종",
    "숙종실록": "숙종",
    "숙종실록보궐정오": "숙종",
    "경종실록": "경종",
    "경종수정실록": "경종",
    "영조실록": "영조",
    "정조실록": "정조",
    "순조실록": "순조",
    "헌종실록": "헌종",
    "철종실록": "철종",
    "고종실록": "고종",
    "순종실록": "순종",
    "순종실록부록": "순종",
}


def get_reign_from_volume(volume: str) -> str:
    """volume 필드에서 실록명 추출 후 왕대명 반환"""
    # "현종실록 5권" → "현종실록" → "현종"
    for sillok_name, reign in SILLOK_TO_REIGN.items():
        if volume.startswith(sillok_name):
            return reign
    return ""


def filter_by_reign_range(entries: list, reign_from: str, reign_to: str) -> list:
    """왕대 범위로 기사 필터링"""
    if not reign_from and not reign_to:
        return entries

    try:
        from_idx = REIGN_ORDER.index(reign_from) if reign_from else 0
        to_idx = REIGN_ORDER.index(reign_to) if reign_to else len(REIGN_ORDER) - 1
    except ValueError as e:
        print(f"경고: 유효하지 않은 왕대명 - {e}")
        return entries

    filtered = []
    for entry in entries:
        reign = get_reign_from_volume(entry['volume'])
        if reign and reign in REIGN_ORDER:
            reign_idx = REIGN_ORDER.index(reign)
            if from_idx <= reign_idx <= to_idx:
                filtered.append(entry)

    return filtered


class SillokSearcher:
    """실록 검색 - requests 기반"""

    ITEMS_PER_PAGE = 50  # 페이지당 항목 수 (사이트 기본값)
    BASE_URL = "https://sillok.history.go.kr"
    SEARCH_URL = "https://sillok.history.go.kr/search/searchResultList.do"

    # 검색 탭 유형
    TAB_ORIGINAL = 'w'  # 원문
    TAB_KOREAN = 'k'    # 국역

    def __init__(self, tab: str = 'w'):
        """
        Args:
            tab: 검색 탭 ('w': 원문, 'k': 국역)
        """
        self.session = None
        self.tab = tab
        self.form_data = {}

    def setup_session(self):
        """HTTP 세션 설정"""
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
        })

    def close(self):
        """세션 종료"""
        if self.session:
            self.session.close()
            self.session = None

    def _extract_form_data(self, soup: BeautifulSoup) -> dict:
        """검색 결과 페이지에서 form 데이터 추출"""
        form_data = {}
        form = soup.find('form', {'name': 'searchForm'})
        if form:
            for inp in form.find_all('input'):
                name = inp.get('name')
                value = inp.get('value', '')
                if name:
                    form_data[name] = value
        return form_data

    def _extract_tab_counts(self, soup: BeautifulSoup) -> dict:
        """탭별 검색 결과 수 추출"""
        counts = {'k': 0, 'w': 0}
        tabs = soup.select('a.cate-item')
        for tab in tabs:
            text = tab.get_text(strip=True)
            href = tab.get('href', '')

            # 국역(1,688) 또는 원문(2,269) 패턴
            match = re.search(r'(국역|원문)\(([\d,]+)\)', text)
            if match:
                tab_type = 'k' if match.group(1) == '국역' else 'w'
                count = int(match.group(2).replace(',', ''))
                counts[tab_type] = count

        return counts

    def search(self, keyword: str) -> int:
        """
        키워드로 검색 실행

        Returns:
            검색 결과 수 (지정된 탭 기준)
        """
        print(f"검색 중: {keyword}")

        # 1단계: 기본 검색으로 form 데이터 획득
        data = {
            'topSearchWord': keyword,
            'pageIndex': '1'
        }

        resp = self.session.post(self.SEARCH_URL, data=data)
        soup = BeautifulSoup(resp.text, 'html.parser')

        # form 데이터 추출
        self.form_data = self._extract_form_data(soup)

        # 탭별 결과 수 확인
        tab_counts = self._extract_tab_counts(soup)

        # 2단계: 원하는 탭으로 전환
        if self.tab != self.form_data.get('type', 'k'):
            self.form_data['type'] = self.tab
            self.form_data['searchType'] = 'kwType'
            self.form_data['pageIndex'] = '1'

            resp = self.session.post(self.SEARCH_URL, data=self.form_data)
            soup = BeautifulSoup(resp.text, 'html.parser')
            self.form_data = self._extract_form_data(soup)

        total_count = tab_counts.get(self.tab, 0)
        tab_name = "국역" if self.tab == 'k' else "원문"
        print(f"  [{tab_name}] → {total_count:,}건 발견")

        return total_count

    def parse_current_page(self, soup: BeautifulSoup) -> list:
        """
        현재 페이지에서 기사 정보 추출

        Returns:
            [{'id': 'kpa_xxx', 'volume': '...', 'date': '...', 'title': '...', 'url': '...'}, ...]
        """
        entries = []

        # a.subject 요소에서 직접 추출
        subjects = soup.select('a.subject')

        for subject in subjects:
            # href에서 기사 ID 추출: javascript:goView('waa_000080', 0);
            href = subject.get('href', '')
            id_match = re.search(r"goView\(['\"](\w+)['\"]", href)
            if not id_match:
                continue

            article_id = id_match.group(1)
            raw_text = subject.get_text(strip=True)

            # 앞의 번호 제거: "1. 태조실록..." → "태조실록..."
            full_text = re.sub(r'^\d+\.\s*', '', raw_text).strip()

            # 파싱: "실록명 N권, 왕대 연월일 간지 N번째기사 / 제목"
            parts = full_text.split(' / ', 1)
            if len(parts) == 2:
                meta_part = parts[0]  # 인조실록 32권, 인조 14년 6월 11일 갑신 1번째기사
                title = parts[1].strip()
            else:
                meta_part = full_text
                title = ""

            # 권수와 날짜 분리
            comma_split = meta_part.split(', ', 1)
            if len(comma_split) == 2:
                volume = comma_split[0].strip()  # 인조실록 32권
                date = comma_split[1].strip()    # 인조 14년 6월 11일 갑신 1번째기사
            else:
                volume = ""
                date = meta_part

            url = f"{self.BASE_URL}/id/{article_id}"

            entries.append({
                'id': article_id,
                'volume': volume,
                'date': date,
                'title': title,
                'url': url
            })

        return entries

    def get_total_pages(self, total_count: int) -> int:
        """총 페이지 수 계산"""
        return (total_count + self.ITEMS_PER_PAGE - 1) // self.ITEMS_PER_PAGE

    def go_to_page(self, page_num: int) -> BeautifulSoup:
        """특정 페이지로 이동"""
        self.form_data['pageIndex'] = str(page_num)
        resp = self.session.post(self.SEARCH_URL, data=self.form_data)
        return BeautifulSoup(resp.text, 'html.parser')

    def search_and_collect(self, keyword: str,
                           limit: int | None = None) -> list:
        """
        키워드 검색 후 모든 페이지에서 결과 수집

        Returns:
            전체 기사 목록
        """
        total_count = self.search(keyword)

        if total_count == 0:
            return []

        all_entries = []
        total_pages = self.get_total_pages(total_count)

        print(f"  총 {total_pages} 페이지 수집 시작...")

        for page in range(1, total_pages + 1):
            soup = self.go_to_page(page)
            entries = self.parse_current_page(soup)
            all_entries.extend(entries)

            if limit and len(all_entries) >= limit:
                all_entries = all_entries[:limit]
                print(f"  → early limit 적용: {len(all_entries)}건 (page {page}/{total_pages})")
                break

            # 진행 상황 출력 (10페이지마다)
            if page % 10 == 0 or page == total_pages:
                print(f"    [{page}/{total_pages}] 수집: {len(all_entries)}건")

            # 서버 부하 방지
            time.sleep(0.3)

        print(f"  → 수집 완료: {len(all_entries)}건")
        return all_entries

    def search_multiple_keywords(self, keywords: list,
                                limit: int | None = None) -> dict:
        """
        복수 키워드 검색 및 수집

        Returns:
            {
                'keywords': ['키워드1', '키워드2', ...],
                'keyword_stats': {'키워드1': 100, '키워드2': 50, ...},
                'entries': [...],  # 중복 제거된 전체 기사
                'total_before_dedup': 150,
            }
        """
        all_entries = []
        seen_ids = set()
        keyword_stats = {}
        total_before_dedup = 0

        for keyword in keywords:
            kw_limit = (limit - len(all_entries)) if limit else None
            entries = self.search_and_collect(keyword, limit=kw_limit)
            keyword_stats[keyword] = len(entries)
            total_before_dedup += len(entries)

            # 중복 제거하면서 추가
            for entry in entries:
                if entry['id'] not in seen_ids:
                    seen_ids.add(entry['id'])
                    all_entries.append(entry)

            if limit and len(all_entries) >= limit:
                break

            # 다음 키워드 검색 전 대기
            if keyword != keywords[-1]:
                time.sleep(1)

        return {
            'keywords': keywords,
            'keyword_stats': keyword_stats,
            'entries': all_entries,
            'total_before_dedup': total_before_dedup
        }

    def count_only(self, keyword: str) -> int:
        """검색 결과 수만 확인 (수집 없이)"""
        return self.search(keyword)


def save_as_tsv(entries: list, output_path: str):
    """TSV 형식으로 저장 (기존 크롤러 호환)"""
    with open(output_path, 'w', encoding='utf-8') as f:
        # 헤더
        f.write("기사ID^권수^날짜^제목^URL\n")
        # 데이터
        for entry in entries:
            f.write(f"{entry['id']}^{entry['volume']}^{entry['date']}^{entry['title']}^{entry['url']}\n")


def save_as_json(entries: list, output_path: str, metadata: dict = None):
    """JSON 형식으로 저장 (메타데이터 포함)"""
    data = {
        'metadata': metadata or {},
        'total_count': len(entries),
        'entries': entries
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser(description='조선왕조실록 검색 스크립트')
    parser.add_argument('--keywords', '-k', required=True,
                        help='검색 키워드 (쉼표로 구분, 예: "광기,狂氣,발광")')
    parser.add_argument('--output', '-o',
                        help='출력 파일 경로')
    parser.add_argument('--format', '-f', choices=['tsv', 'json'], default='tsv',
                        help='출력 형식 (기본: tsv)')
    parser.add_argument('--count-only', '-c', action='store_true',
                        help='검색 결과 수만 확인 (다운로드 없이)')
    parser.add_argument('--tab', '-t', choices=['w', 'k'], default='w',
                        help='검색 탭 (w: 원문, k: 국역, 기본: w)')
    parser.add_argument('--reign-from', '-rf',
                        help='시작 왕대 (예: 현종)')
    parser.add_argument('--reign-to', '-rt',
                        help='종료 왕대 (예: 영조)')

    args = parser.parse_args()

    # 키워드 파싱
    keywords = [k.strip() for k in args.keywords.split(',') if k.strip()]

    if not keywords:
        print("키워드를 입력해주세요.")
        sys.exit(1)

    if not args.count_only and not args.output:
        print("출력 파일 경로를 지정해주세요. (--output)")
        sys.exit(1)

    tab_name = "국역" if args.tab == 'k' else "원문"
    reign_from = args.reign_from
    reign_to = args.reign_to

    print(f"검색 키워드: {keywords}")
    print(f"검색 탭: {tab_name}")
    if reign_from or reign_to:
        reign_range = f"{reign_from or '태조'}~{reign_to or '순종'}"
        print(f"왕대 범위: {reign_range}")
    if not args.count_only:
        print(f"출력 파일: {args.output}")
        print(f"출력 형식: {args.format}")
    print()

    # 검색 실행
    searcher = SillokSearcher(tab=args.tab)

    try:
        searcher.setup_session()

        if args.count_only:
            # 검색 결과 수만 확인
            total = 0
            for keyword in keywords:
                count = searcher.count_only(keyword)
                total += count
            print(f"\n총 {total:,}건 (중복 포함)")
        else:
            # 복수 키워드 검색 및 수집
            search_result = searcher.search_multiple_keywords(keywords)

            print()
            print("=" * 50)
            print("검색 완료")
            print(f"  키워드별 결과: {search_result['keyword_stats']}")
            print(f"  총 결과 (중복 포함): {search_result['total_before_dedup']}건")
            print(f"  중복 제거 후: {len(search_result['entries'])}건")

            # 왕대 범위 필터링
            entries = search_result['entries']
            if reign_from or reign_to:
                entries = filter_by_reign_range(entries, reign_from, reign_to)
                print(f"  왕대 필터링 후: {len(entries)}건")

            # 저장
            if args.format == 'tsv':
                save_as_tsv(entries, args.output)
            else:
                metadata = {
                    'search_date': datetime.now().isoformat(),
                    'keywords': keywords,
                    'tab': args.tab,
                    'tab_name': tab_name,
                    'keyword_stats': search_result['keyword_stats'],
                    'total_before_dedup': search_result['total_before_dedup']
                }
                save_as_json(entries, args.output, metadata)

            print(f"\n저장 완료: {args.output}")

    finally:
        searcher.close()


if __name__ == '__main__':
    main()